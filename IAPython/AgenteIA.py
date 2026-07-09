# agente_ia_greenhealth_planilha_real.py
# GreenHealth - Agente inteligente externo com base na sua planilha real
#
# Instalar:
#   pip install paho-mqtt pandas openpyxl
#
# Rodar:
#   python agente_ia_greenhealth_planilha_real.py
#
# Este agente foi adaptado para uma planilha com colunas como:
# ID, Planta / nome popular, Luminosidade ideal, Temperatura ideal (°C),
# Umidade do ar ideal (%), Umidade solo ideal (%), Irrigar abaixo (%),
# Alerta excesso (%), Frequência de rega aproximada, Observações para IoT etc.
#
# Ele:
# - Lê a planilha de perfis botânicos
# - Escuta os sensores em MQTT
# - Decide se deve regar com base em umidade do solo + frequência de rega
# - Publica comandos para o servo
# - Publica dicas e alertas sobre luz, temperatura, umidade do ar e excesso de água


import json
import math
import os
import random
import re
import signal
import sys
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import paho.mqtt.client as mqtt


# Evita caracteres quebrados no terminal do Windows, como N�O em vez de NÃO.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


# =========================================================
# CONFIGURAÇÕES MQTT
# =========================================================

MQTT_BROKER = "broker.emqx.io"
MQTT_PORT = 1883

# IMPORTANTE:
# Use um client ID único para não derrubar ESP32, dashboard ou Node-RED.
MQTT_CLIENT_ID = f"greenhealth_ia_{random.randint(10000, 99999)}"

TOPICO_SENSORES_JSON = "greenhealth/sensores/dados"

# Assina todos os tópicos do GreenHealth para conseguir ver os envios individuais
# e o JSON agregado. A IA só PROCESSA o JSON completo em TOPICO_SENSORES_JSON.
TOPICO_SENSORES = "greenhealth/#"

# A IA só vai processar/publicar retorno no DashboardIA a cada 5 segundos.
INTERVALO_RETORNO_IA_SEG = 5

# A IA pode receber os sensores de duas formas:
# 1) JSON agregado: greenhealth/sensores/dados -> {"plantas": [...]}
# 2) Tópicos individuais: greenhealth/planta1/ldr, greenhealth/planta1/umidade, etc.
#
# Ela monta/guarda o último payload válido e republica a análise
# a cada INTERVALO_RETORNO_IA_SEG segundos.
ultimo_payload_sensores: Optional[Dict[str, Any]] = None
ultimo_topico_sensores: str = TOPICO_SENSORES_JSON
ultimo_payload_lock = threading.Lock()

# Buffer para montar o JSON a partir dos tópicos individuais.
buffer_sensores_individuais: Dict[str, Any] = {
    "plantas": {},
    "temperatura": None,
    "umidade_ar": None,
    "data_hora": None,
    "ultima_atualizacao": None,
}

TOPICO_SERVO_BASE = "greenhealth/atuadores"
TOPICO_DECISOES = "greenhealth/ia/decisoes"
TOPICO_ALERTAS = "greenhealth/ia/alertas"
TOPICO_DICAS = "greenhealth/ia/dicas"
TOPICO_PREVISAO = "greenhealth/ia/previsao"
TOPICO_STATUS = "greenhealth/ia/status"


# =========================================================
# CONFIGURAÇÕES DA PLANILHA
# =========================================================

# Coloque sua planilha na mesma pasta deste arquivo.
# Pode ser .xlsx, .csv ou .txt em formato CSV.
PLANILHA_PERFIS = r"IAPython\perfis_plantas.csv"

# Se o arquivo acima não existir, o código tenta encontrar automaticamente.
ARQUIVOS_ALTERNATIVOS_PLANILHA = [
    "perfis_plantas.xlsx",
    "perfis_plantas.csv",
    "plantas.xlsx",
    "plantas.csv",
    "Texto colado(30).txt",
]

# Recarrega a planilha a cada X segundos.
INTERVALO_RECARREGAR_PLANILHA_SEG = 30


# =========================================================
# MAPEAMENTO ENTRE VASOS FÍSICOS E IDs DA PLANILHA
# =========================================================
#
# Seu ESP32 normalmente envia:
#
# "plantas": [
#   { "planta": 1, "umidade_solo": 35, "ldr": 2800 },
#   { "planta": 2, "umidade_solo": 60, "ldr": 1900 }
# ]
#
# Porém sua planilha tem IDs botânicos próprios:
# Exemplo:
# ID 24 = Jiboia
# ID 9  = Espada-de-são-jorge
# ID 14 = Manjericão
#
# Então configure aqui qual vaso físico usa qual ID da planilha.
#
# Exemplo abaixo:
# vaso/planta 1 do ESP32 = ID 24 da planilha = Jiboia
# vaso/planta 2 do ESP32 = ID 9 da planilha = Espada-de-são-jorge
# vaso/planta 3 do ESP32 = ID 14 da planilha = Manjericão

MAPEAMENTO_VASO_PARA_ID_PLANILHA = {
    1: 18,
    2:24,
    3: 42,
}

# Se seu ESP32 já enviar o ID real da planilha no JSON como "id_planilha",
# "id_botanico" ou "perfil_id", esse mapeamento não será necessário.


# =========================================================
# CONFIGURAÇÕES DE REGA
# =========================================================

MODO_AUTOMATICO_REGA = True

ANGULO_SERVO_REGA_PADRAO = 90
ANGULO_SERVO_FECHADO = 0

# Trava para evitar repetir o comando várias vezes em sequência.
INTERVALO_MINIMO_ENTRE_COMANDOS_SEG = 1

# Se a umidade estiver MUITO baixa, permite rega emergencial mesmo antes
# da frequência aproximada terminar.
# Exemplo: irrigar abaixo = 35. Emergencial se umidade < 35 * 0.70 = 24.5.
FATOR_REGA_EMERGENCIAL = 0.70

# Estado local para lembrar últimas regas.
ARQUIVO_ESTADO = "estado_regas_ia.json"


# =========================================================
# UTILITÁRIOS
# =========================================================

def agora_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def normalizar_texto(txt: Any) -> str:
    txt = str(txt).strip().lower()
    trocas = {
        "á": "a", "à": "a", "ã": "a", "â": "a",
        "é": "e", "ê": "e",
        "í": "i",
        "ó": "o", "ô": "o", "õ": "o",
        "ú": "u",
        "ç": "c",
        "º": "",
        "°": "",
        "/": "_",
        "\\": "_",
        "-": "_",
        "–": "_",
        "—": "_",
        "(": "",
        ")": "",
        "%": "",
        ".": "",
        ",": "",
        " ": "_",
    }
    for a, b in trocas.items():
        txt = txt.replace(a, b)
    while "__" in txt:
        txt = txt.replace("__", "_")
    return txt.strip("_")


def valor_numero(valor: Any, padrao: Optional[float] = None) -> Optional[float]:
    if valor is None:
        return padrao

    if isinstance(valor, float) and math.isnan(valor):
        return padrao

    if isinstance(valor, int) or isinstance(valor, float):
        return float(valor)

    texto = str(valor).strip().replace(",", ".")
    if texto == "" or texto.lower() in ["nan", "none", "null"]:
        return padrao

    # Pega o primeiro número encontrado no texto.
    m = re.search(r"[-+]?\d+(?:\.\d+)?", texto)
    if not m:
        return padrao

    try:
        return float(m.group(0))
    except Exception:
        return padrao


def valor_inteiro(valor: Any, padrao: Optional[int] = None) -> Optional[int]:
    n = valor_numero(valor, None)
    if n is None:
        return padrao
    return int(n)


def normalizar_lista(valor: Any) -> List[str]:
    """
    Converte None/string/lista em lista de strings, removendo vazios.
    Ajuda a publicar alertas e notificações no formato esperado pelo DashboardIA.
    """
    if valor is None:
        return []

    if isinstance(valor, list):
        itens = valor
    else:
        itens = [valor]

    saida: List[str] = []
    for item in itens:
        texto = str(item).strip()
        if texto:
            saida.append(texto)

    return saida


def remover_codigo_inicial(texto: Any) -> str:
    """
    Remove prefixos do tipo:
    (1) Baixa a média indireta
    (6) 5–10 dias
    """
    if texto is None:
        return ""
    s = str(texto).strip()
    s = re.sub(r"^\s*\(\s*\d+\s*\)\s*", "", s)
    return s.strip()


def parse_intervalo(texto: Any, padrao_min: Optional[float], padrao_max: Optional[float]) -> Tuple[Optional[float], Optional[float]]:
    """
    Lê valores como:
    18–27
    40–60
    50–70+
    "35–60"
    "Média/alta indireta" -> usa padrão
    """
    if texto is None:
        return padrao_min, padrao_max

    s = remover_codigo_inicial(texto)
    s = s.replace(",", ".")
    s = s.replace("–", "-").replace("—", "-")

    nums = re.findall(r"\d+(?:\.\d+)?", s)

    if len(nums) >= 2:
        minimo = float(nums[0])
        maximo = float(nums[1])

        # Se tiver 70+, considera que não precisa alertar excesso tão cedo.
        if "+" in s:
            maximo = 100.0

        return minimo, maximo

    if len(nums) == 1:
        n = float(nums[0])
        return n, padrao_max

    return padrao_min, padrao_max


def parse_dias_frequencia(texto: Any, padrao: float = 1.0) -> float:
    """
    Lê a frequência de rega aproximada da sua planilha.
    Exemplos:
    "(6) 5–10 dias, sempre validando o solo" -> 5
    "(7) 14–21 dias ou quando o solo secar" -> 14
    "(1) Borrifar/imersão semanal ou substrato aerado" -> 7
    """
    if texto is None:
        return padrao

    s = remover_codigo_inicial(texto).lower()
    s = s.replace(",", ".")
    s = s.replace("–", "-").replace("—", "-")

    nums = re.findall(r"\d+(?:\.\d+)?", s)

    if len(nums) >= 1:
        # Usa o menor número como intervalo mínimo entre regas.
        return float(nums[0])

    if "semanal" in s or "semana" in s:
        return 7.0

    if "diaria" in s or "diário" in s or "diario" in s or "todo dia" in s:
        return 1.0

    return padrao


def parse_luminosidade(texto: Any) -> Tuple[float, float, str]:
    """
    A sua planilha descreve luminosidade com categorias textuais:
    (1) Baixa a média indireta
    (2) Média indireta / meia-sombra clara
    (3) Média a alta indireta
    (4) Média/alta indireta, sem sol forte direto
    (5) Alta indireta / filtrada
    (6) Alta / sol filtrado ou luz muito forte
    (7) Alta / várias horas de luz

    Como o sensor entrega porcentagem, convertemos essas categorias em faixas.
    Ajuste os valores se seu LDR estiver calibrado de outro jeito.
    """
    bruto = "" if texto is None else str(texto).strip()
    s = bruto.lower()

    m = re.search(r"\((\d+)\)", s)
    codigo = int(m.group(1)) if m else None

    faixas = {
        1: (15.0, 70.0, "baixa a média indireta"),
        2: (30.0, 75.0, "média indireta / meia-sombra clara"),
        3: (40.0, 85.0, "média a alta indireta"),
        4: (45.0, 80.0, "média/alta indireta sem sol forte direto"),
        5: (55.0, 90.0, "alta indireta / filtrada"),
        6: (65.0, 100.0, "alta / sol filtrado ou luz muito forte"),
        7: (70.0, 100.0, "alta / várias horas de luz"),
    }

    if codigo in faixas:
        return faixas[codigo]

    # Fallback por palavras-chave.
    s_norm = normalizar_texto(s)

    if "baixa" in s_norm and "media" in s_norm:
        return 15.0, 70.0, "baixa a média indireta"
    if "media" in s_norm and "alta" in s_norm:
        return 40.0, 85.0, "média a alta indireta"
    if "alta" in s_norm:
        return 60.0, 100.0, "alta luminosidade"
    if "media" in s_norm:
        return 30.0, 75.0, "média luminosidade"
    if "baixa" in s_norm:
        return 10.0, 55.0, "baixa luminosidade"

    return 30.0, 85.0, bruto or "luminosidade padrão"


def converter_ldr_para_luminosidade_pct(ldr: Optional[float]) -> Optional[float]:
    """
    ESP32 ADC: 0 a 4095.

    LDR normal:
    - 0 = 0% luz
    - 4095 = 100% luz
    """
    if ldr is None:
        return None

    ldr = max(0.0, min(4095.0, float(ldr)))
    return round((ldr / 4095.0) * 100.0, 2)


def converter_umidade_solo_para_pct(valor: Optional[float]) -> Optional[float]:
    """
    Sensor de umidade do solo analógico invertido.

    ESP32 ADC: 0 a 4095/4096.

    No seu sensor:
    - valor baixo = mais úmido
    - valor alto = mais seco

    Conversão usada pela IA:
    - 0 = 100% de umidade
    - 4095 = 0% de umidade
    """
    if valor is None:
        return None

    valor = max(0.0, min(4095.0, float(valor)))
    return round(100.0 - ((valor / 4095.0) * 100.0), 2)



def carregar_json(caminho: str, padrao: Any) -> Any:
    if not os.path.exists(caminho):
        return padrao
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return padrao


def salvar_json(caminho: str, dados: Any) -> None:
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def ler_dataframe_generico(caminho: str) -> pd.DataFrame:
    """
    Lê .xlsx, .csv ou .txt de forma mais tolerante.

    Isso corrige dois problemas comuns:
    1) o código abrir uma planilha antiga/exemplo por engano;
    2) CSV com acentos ou separador diferente quebrar a leitura.
    """
    lower = caminho.lower()

    if lower.endswith(".xlsx") or lower.endswith(".xls"):
        return pd.read_excel(caminho)

    tentativas = [
        {"sep": None, "engine": "python", "encoding": "utf-8-sig"},
        {"sep": None, "engine": "python", "encoding": "utf-8"},
        {"sep": ",", "engine": "python", "encoding": "utf-8-sig"},
        {"sep": ";", "engine": "python", "encoding": "utf-8-sig"},
        {"sep": ",", "engine": "python", "encoding": "latin1"},
        {"sep": ";", "engine": "python", "encoding": "latin1"},
    ]

    ultimo_erro = None

    for params in tentativas:
        try:
            return pd.read_csv(caminho, **params)
        except Exception as e:
            ultimo_erro = e

    raise ultimo_erro


def listar_arquivos_candidatos_planilha() -> List[str]:
    candidatos: List[str] = []

    def adicionar(caminho: str) -> None:
        if caminho and os.path.exists(caminho) and caminho not in candidatos:
            candidatos.append(caminho)

    adicionar(PLANILHA_PERFIS)

    for arquivo in ARQUIVOS_ALTERNATIVOS_PLANILHA:
        adicionar(arquivo)

    # Busca também qualquer planilha/CSV/TXT da pasta atual.
    for arquivo in os.listdir("."):
        lower = arquivo.lower()
        if lower.endswith(".xlsx") or lower.endswith(".xls") or lower.endswith(".csv") or lower.endswith(".txt"):
            adicionar(arquivo)

    return candidatos


def ids_encontrados_no_arquivo(caminho: str) -> List[int]:
    """
    Tenta abrir o arquivo e retornar IDs da coluna ID.
    Se não achar a coluna ID, retorna lista vazia.
    """
    try:
        df = ler_dataframe_generico(caminho)
        df.columns = [normalizar_texto(c) for c in df.columns]

        if "id" not in df.columns:
            return []

        ids: List[int] = []

        for valor in df["id"].tolist():
            n = valor_inteiro(valor)
            if n is not None:
                ids.append(n)

        return ids

    except Exception:
        return []


def encontrar_planilha() -> Optional[str]:
    """
    Escolhe a planilha certa.

    Antes o código podia abrir uma planilha exemplo antiga, como perfis_plantas.xlsx
    com IDs 1, 2 e 3. Agora ele procura uma planilha que contenha os IDs
    configurados em MAPEAMENTO_VASO_PARA_ID_PLANILHA, como 24, 18 e 42.
    """
    candidatos = listar_arquivos_candidatos_planilha()

    if not candidatos:
        return None

    ids_esperados = set(MAPEAMENTO_VASO_PARA_ID_PLANILHA.values())

    melhor_arquivo = None
    melhor_pontuacao = -1
    melhor_ids: List[int] = []

    for arquivo in candidatos:
        ids = ids_encontrados_no_arquivo(arquivo)
        pontuacao = len(ids_esperados.intersection(set(ids)))

        if pontuacao > melhor_pontuacao:
            melhor_pontuacao = pontuacao
            melhor_arquivo = arquivo
            melhor_ids = ids

        # Achou todos os IDs esperados. É a base correta.
        if ids_esperados and ids_esperados.issubset(set(ids)):
            print(f"[OK] Planilha escolhida por conter os IDs esperados {sorted(ids_esperados)}: {arquivo}")
            return arquivo

    if melhor_arquivo and melhor_pontuacao > 0:
        print(
            f"[AVISO] Nenhuma planilha contém todos os IDs esperados {sorted(ids_esperados)}. "
            f"Usando a que mais se aproxima: {melhor_arquivo}. "
            f"IDs encontrados nela: {sorted(set(melhor_ids))[:20]}"
        )
        return melhor_arquivo

    # Fallback: usa o primeiro candidato, mas avisa.
    print(
        f"[AVISO] Não encontrei nenhuma planilha com os IDs esperados {sorted(ids_esperados)}. "
        f"Vou abrir o primeiro arquivo candidato: {candidatos[0]}"
    )
    return candidatos[0]


# =========================================================
# LEITOR DA PLANILHA REAL
# =========================================================

class BaseConhecimentoPlantas:
    def __init__(self) -> None:
        self.caminho: Optional[str] = None
        self.perfis: Dict[int, Dict[str, Any]] = {}
        self.ultima_carga = 0.0

    def precisa_recarregar(self) -> bool:
        return (time.time() - self.ultima_carga) >= INTERVALO_RECARREGAR_PLANILHA_SEG

    def _ler_dataframe(self, caminho: str) -> pd.DataFrame:
        return ler_dataframe_generico(caminho)

    def carregar(self, forcar: bool = False) -> None:
        if not forcar and not self.precisa_recarregar():
            return

        caminho = encontrar_planilha()

        if not caminho:
            print("[ERRO] Nenhuma planilha encontrada na pasta.")
            print("[DICA] Salve sua base como perfis_plantas.csv ou perfis_plantas.xlsx na mesma pasta do script.")
            self.ultima_carga = time.time()
            return

        try:
            df = self._ler_dataframe(caminho)
            df.columns = [normalizar_texto(c) for c in df.columns]

            print(f"[INFO] Arquivo de planilha aberto: {caminho}")
            print(f"[INFO] Colunas detectadas: {list(df.columns)}")

            if "id" not in df.columns:
                print("[ERRO] A coluna ID não foi encontrada depois da normalização.")
                print("[DICA] Confira se a primeira coluna da sua base se chama exatamente ID.")

            perfis: Dict[int, Dict[str, Any]] = {}

            for _, linha in df.iterrows():
                row = linha.to_dict()

                id_planilha = valor_inteiro(row.get("id"))
                if id_planilha is None:
                    continue

                nome = str(
                    row.get("planta_nome_popular")
                    or row.get("planta")
                    or row.get("nome_popular")
                    or f"Planta {id_planilha}"
                ).strip()

                nome_cientifico = str(
                    row.get("nome_cientifico_grupo")
                    or row.get("nome_cientifico")
                    or ""
                ).strip()

                perfil_botanico = str(row.get("perfil_botanico_sugerido") or "").strip()
                caracteristicas = str(row.get("caracteristicas_atualizadas") or "").strip()
                obs_iot = str(row.get("observacoes_para_iot") or "").strip()
                confianca = str(row.get("confianca_do_parametro") or "").strip()

                temp_min, temp_max = parse_intervalo(
                    row.get("temperatura_ideal_c") or row.get("temperatura_ideal"),
                    18.0,
                    32.0
                )

                ar_min, ar_max = parse_intervalo(
                    row.get("umidade_do_ar_ideal") or row.get("umidade_ar_ideal"),
                    40.0,
                    80.0
                )

                solo_min, solo_max = parse_intervalo(
                    row.get("umidade_solo_ideal"),
                    35.0,
                    75.0
                )

                irrigar_abaixo = valor_numero(row.get("irrigar_abaixo"), solo_min)
                alerta_excesso = valor_numero(row.get("alerta_excesso"), solo_max)

                luz_min, luz_max, luz_desc = parse_luminosidade(row.get("luminosidade_ideal"))

                dias_minimos = parse_dias_frequencia(
                    row.get("frequencia_de_rega_aproximada"),
                    padrao=1.0
                )

                perfis[id_planilha] = {
                    "id_planilha": id_planilha,
                    "nome": nome,
                    "nome_cientifico": nome_cientifico,
                    "perfil_botanico": perfil_botanico,
                    "caracteristicas": caracteristicas,
                    "luminosidade_descricao": luz_desc,
                    "luminosidade_min": luz_min,
                    "luminosidade_max": luz_max,
                    "temperatura_min": temp_min,
                    "temperatura_max": temp_max,
                    "umidade_ar_min": ar_min,
                    "umidade_ar_max": ar_max,
                    "umidade_solo_min": solo_min,
                    "umidade_solo_max": solo_max,
                    "irrigar_abaixo": irrigar_abaixo,
                    "alerta_excesso": alerta_excesso,
                    "dias_entre_regas": dias_minimos,
                    "frequencia_original": str(row.get("frequencia_de_rega_aproximada") or "").strip(),
                    "observacoes_iot": obs_iot,
                    "confianca": confianca,
                }

            self.caminho = caminho
            self.perfis = perfis
            self.ultima_carga = time.time()

            print(f"[OK] Base de conhecimento carregada: {caminho}")
            print(f"[OK] Perfis encontrados: {len(self.perfis)}")
            ids_disponiveis = sorted(self.perfis.keys())
            print(f"[INFO] Primeiros IDs disponíveis: {ids_disponiveis[:20]}")

        except Exception as e:
            print(f"[ERRO] Falha ao carregar planilha: {e}")
            self.ultima_carga = time.time()

    def obter_por_id(self, id_planilha: int) -> Optional[Dict[str, Any]]:
        self.carregar()
        return self.perfis.get(int(id_planilha))


# =========================================================
# AGENTE INTELIGENTE
# =========================================================

class AgenteGreenHealthIA:
    def __init__(self, client: mqtt.Client, base: BaseConhecimentoPlantas) -> None:
        self.client = client
        self.base = base
        self.estado = carregar_json(ARQUIVO_ESTADO, {
            "ultimas_regas": {},
            "ultimos_comandos": {}
        })

    def publicar_json(self, topico: str, dados: Dict[str, Any], retain: bool = True) -> None:
        """
        Publica JSON para o DashboardIA com QoS 1 e retain por padrão.

        O retain ajuda quando o DashboardIA é aberto depois da IA processar:
        ele recebe a última decisão/alerta/dica/previsão salva no broker.
        """
        payload = json.dumps(dados, ensure_ascii=False)

        info = self.client.publish(
            topico,
            payload,
            qos=1,
            retain=retain
        )

        try:
            info.wait_for_publish(timeout=2)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                print(f"[ERRO MQTT] Falha ao publicar em {topico}. Código: {info.rc}")
        except Exception as e:
            print(f"[ERRO MQTT] Publicação não confirmada em {topico}: {e}")

    def publicar_status(self, status: str, extra: Optional[Dict[str, Any]] = None) -> None:
        dados = {
            "status": status,
            "data_hora": agora_iso()
        }
        if extra:
            dados.update(extra)
        self.publicar_json(TOPICO_STATUS, dados, retain=True)

    def salvar_estado(self) -> None:
        salvar_json(ARQUIVO_ESTADO, self.estado)

    def resolver_id_planilha(self, leitura_planta: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
        """
        Retorna:
        - id_vaso: número físico enviado pelo ESP32
        - id_planilha: ID da base de conhecimento
        """
        id_vaso = valor_inteiro(
            leitura_planta.get("planta")
            or leitura_planta.get("vaso")
            or leitura_planta.get("id_vaso")
        )

        id_planilha = valor_inteiro(
            leitura_planta.get("id_planilha")
            or leitura_planta.get("id_botanico")
            or leitura_planta.get("perfil_id")
        )

        if id_planilha is None and id_vaso is not None:
            id_planilha = MAPEAMENTO_VASO_PARA_ID_PLANILHA.get(id_vaso)

        # Se não houver mapeamento, assume que "planta" já é o ID da planilha.
        if id_planilha is None and id_vaso is not None:
            id_planilha = id_vaso

        return id_vaso, id_planilha

    def dias_desde_ultima_rega(self, id_vaso: int) -> Optional[float]:
        ultima = self.estado.get("ultimas_regas", {}).get(str(id_vaso))
        if not ultima:
            return None

        try:
            dt = datetime.fromisoformat(ultima)
            return (datetime.now() - dt).total_seconds() / 86400.0
        except Exception:
            return None

    def pode_enviar_comando(self, id_vaso: int) -> Tuple[bool, str]:
        ultimo = self.estado.get("ultimos_comandos", {}).get(str(id_vaso))
        if not ultimo:
            return True, "Sem comando anterior."

        try:
            dt = datetime.fromisoformat(ultimo)
            diff = (datetime.now() - dt).total_seconds()
            if diff < INTERVALO_MINIMO_ENTRE_COMANDOS_SEG:
                return False, f"Comando bloqueado. Último comando há {int(diff)} segundos."
        except Exception:
            return True, "Registro anterior inválido."

        return True, "Comando permitido."

    def registrar_rega(self, id_vaso: int) -> None:
        self.estado.setdefault("ultimas_regas", {})[str(id_vaso)] = agora_iso()
        self.estado.setdefault("ultimos_comandos", {})[str(id_vaso)] = agora_iso()
        self.salvar_estado()

    def enviar_servo(self, id_vaso: int, angulo: int) -> None:
        topico = f"{TOPICO_SERVO_BASE}/planta{id_vaso}/servo"
        self.client.publish(topico, str(int(angulo)), qos=0, retain=False)
        print(f"[MQTT] Servo enviado: {topico} -> {angulo}")

    def avaliar_planta(self, leitura_planta: Dict[str, Any], dados_gerais: Dict[str, Any]) -> Dict[str, Any]:
        id_vaso, id_planilha = self.resolver_id_planilha(leitura_planta)

        if id_vaso is None:
            id_vaso = id_planilha

        if id_planilha is None:
            return {
                "tipo": "erro",
                "data_hora": agora_iso(),
                "acao": "sem_id",
                "regar": False,
                "alertas": ["Não foi possível identificar a planta recebida no MQTT."],
                "dicas": ["Envie no JSON o campo 'planta', 'id_planilha' ou configure MAPEAMENTO_VASO_PARA_ID_PLANILHA."]
            }

        perfil = self.base.obter_por_id(id_planilha)

        if perfil is None:
            return {
                "tipo": "erro",
                "data_hora": agora_iso(),
                "vaso": id_vaso,
                "id_planilha": id_planilha,
                "acao": "sem_perfil",
                "regar": False,
                "alertas": [f"Não encontrei o ID {id_planilha} na planilha."],
                "dicas": ["Confira se o ID existe na coluna ID da base de conhecimento."]
            }

        temperatura = valor_numero(dados_gerais.get("temperatura"))
        umidade_ar = valor_numero(dados_gerais.get("umidade_ar"))

        umidade_solo_raw = valor_numero(
            leitura_planta.get("umidade_solo")
            if leitura_planta.get("umidade_solo") is not None
            else leitura_planta.get("umidade")
        )

        # O sensor de umidade do solo envia ADC invertido:
        # valor alto = menos umidade, valor baixo = mais umidade.
        # A IA compara com a planilha em porcentagem real de umidade.
        umidade_solo = converter_umidade_solo_para_pct(umidade_solo_raw)

        luminosidade = valor_numero(
            leitura_planta.get("luminosidade")
            if leitura_planta.get("luminosidade") is not None
            else leitura_planta.get("luz")
        )

        ldr = valor_numero(leitura_planta.get("ldr"))
        if luminosidade is None and ldr is not None:
            luminosidade = converter_ldr_para_luminosidade_pct(ldr)

        nome = perfil["nome"]

        alertas: List[str] = []
        dicas: List[str] = []
        motivos_rega: List[str] = []

        # -------------------------
        # UMIDADE DO SOLO / REGA
        # -------------------------
        irrigar_abaixo = perfil["irrigar_abaixo"]
        alerta_excesso = perfil["alerta_excesso"]

        if umidade_solo is None:
            alertas.append(f"Sem leitura de umidade do solo para {nome}.")
        else:
            if umidade_solo < irrigar_abaixo:
                motivos_rega.append(
                    f"Umidade do solo em {umidade_solo:.1f}%, abaixo do limite de irrigação ({irrigar_abaixo:.1f}%)."
                )
                dicas.append(f"A {nome} precisa de irrigação controlada.")
            elif umidade_solo >= alerta_excesso:
                alertas.append(
                    f"Possível excesso de água em {nome}: solo em {umidade_solo:.1f}%, alerta acima de {alerta_excesso:.1f}%."
                )
                dicas.append("Evite nova rega agora. Verifique drenagem do vaso e risco de encharcamento.")
            else:
                dicas.append(
                    f"Solo dentro da faixa aceitável para {nome}: {umidade_solo:.1f}%."
                )

        # -------------------------
        # FREQUÊNCIA / DIAS DE REGA
        # -------------------------
        dias_minimos = perfil["dias_entre_regas"]
        dias_passados = self.dias_desde_ultima_rega(int(id_vaso)) if id_vaso is not None else None

        bloqueado_por_dias = False
        if dias_passados is not None and dias_passados < dias_minimos:
            bloqueado_por_dias = True
            restante = dias_minimos - dias_passados
            dicas.append(
                f"Frequência da planilha: {perfil['frequencia_original']}. "
                f"Última rega há {dias_passados:.2f} dia(s). "
                f"Faltam cerca de {restante:.2f} dia(s) para o intervalo mínimo."
            )

        rega_emergencial = False
        if umidade_solo is not None:
            rega_emergencial = umidade_solo < (irrigar_abaixo * FATOR_REGA_EMERGENCIAL)

        deve_regar = False
        if motivos_rega:
            if not bloqueado_por_dias or rega_emergencial:
                deve_regar = True
            else:
                alertas.append(
                    f"{nome} está abaixo do ideal de umidade, mas a rega automática foi bloqueada pela frequência mínima."
                )

        # -------------------------
        # TEMPERATURA
        # -------------------------
        temp_min = perfil["temperatura_min"]
        temp_max = perfil["temperatura_max"]

        if temperatura is None:
            alertas.append("Sem leitura de temperatura ambiente.")
        else:
            if temperatura < temp_min:
                alertas.append(
                    f"Temperatura baixa para {nome}: {temperatura:.1f}°C. Ideal: {temp_min:.1f}–{temp_max:.1f}°C."
                )
                dicas.append("Mova para um local menos frio ou mais protegido de vento.")
            elif temperatura > temp_max:
                alertas.append(
                    f"Temperatura alta para {nome}: {temperatura:.1f}°C. Ideal: {temp_min:.1f}–{temp_max:.1f}°C."
                )
                dicas.append("Evite sol direto forte e monitore se o solo está secando rápido.")
            else:
                dicas.append(f"Temperatura adequada para {nome}: {temperatura:.1f}°C.")

        # -------------------------
        # UMIDADE DO AR
        # -------------------------
        ar_min = perfil["umidade_ar_min"]
        ar_max = perfil["umidade_ar_max"]

        if umidade_ar is None:
            alertas.append("Sem leitura de umidade do ar.")
        else:
            if umidade_ar < ar_min:
                alertas.append(
                    f"Umidade do ar baixa para {nome}: {umidade_ar:.1f}%. Ideal: {ar_min:.1f}–{ar_max:.1f}%."
                )
                dicas.append("Aumente a umidade do ambiente, agrupe plantas ou use bandeja com pedras e água.")
            elif umidade_ar > ar_max:
                alertas.append(
                    f"Umidade do ar alta para {nome}: {umidade_ar:.1f}%. Ideal: {ar_min:.1f}–{ar_max:.1f}%."
                )
                dicas.append("Melhore a ventilação para reduzir risco de fungos.")
            else:
                dicas.append(f"Umidade do ar adequada para {nome}: {umidade_ar:.1f}%.")

        # -------------------------
        # LUMINOSIDADE
        # -------------------------
        luz_min = perfil["luminosidade_min"]
        luz_max = perfil["luminosidade_max"]
        luz_desc = perfil["luminosidade_descricao"]

        if luminosidade is None:
            alertas.append("Sem leitura de luminosidade.")
        else:
            if luminosidade < luz_min:
                alertas.append(
                    f"Luminosidade baixa para {nome}: {luminosidade:.1f}%. Ideal: {luz_desc}."
                )
                dicas.append("Aproxime de uma janela ou melhore a luz indireta do ambiente.")
            elif luminosidade > luz_max:
                alertas.append(
                    f"Luminosidade alta para {nome}: {luminosidade:.1f}%. Ideal: {luz_desc}."
                )
                dicas.append("Evite sol direto prolongado ou use luz filtrada.")
            else:
                dicas.append(f"Luminosidade adequada para {nome}: {luminosidade:.1f}% ({luz_desc}).")

        # Observações da planilha entram como dica.
        if perfil.get("observacoes_iot"):
            dicas.append(f"Observação IoT: {perfil['observacoes_iot']}")

        if perfil.get("caracteristicas"):
            dicas.append(f"Característica da planta: {perfil['caracteristicas']}")

        acao = "regar" if deve_regar else "nao_regar"

        return {
            "tipo": "decisao_ia_greenhealth",
            "data_hora": agora_iso(),
            "vaso": id_vaso,
            "id_planilha": id_planilha,
            "nome": nome,
            "nome_cientifico": perfil["nome_cientifico"],
            "perfil_botanico": perfil["perfil_botanico"],
            "acao": acao,
            "regar": deve_regar,
            "angulo_servo": ANGULO_SERVO_REGA_PADRAO if deve_regar else ANGULO_SERVO_FECHADO,
            "motivos_rega": motivos_rega,
            "alertas": alertas,
            "dicas": dicas,
            "leituras": {
                # Valor convertido para porcentagem real, usado na decisão.
                "umidade_solo": umidade_solo,

                # Valor bruto recebido do ESP32, útil para conferência no console/dashboard.
                "umidade_solo_raw": umidade_solo_raw,

                "temperatura": temperatura,
                "umidade_ar": umidade_ar,
                "luminosidade": luminosidade,
                "ldr": ldr,
            },
            "limites_usados": {
                "irrigar_abaixo": irrigar_abaixo,
                "alerta_excesso": alerta_excesso,
                "umidade_solo_ideal_min": perfil["umidade_solo_min"],
                "umidade_solo_ideal_max": perfil["umidade_solo_max"],
                "temperatura_min": temp_min,
                "temperatura_max": temp_max,
                "umidade_ar_min": ar_min,
                "umidade_ar_max": ar_max,
                "luminosidade_min": luz_min,
                "luminosidade_max": luz_max,
                "dias_entre_regas": dias_minimos,
                "frequencia_original": perfil["frequencia_original"],
            },
            "seguranca": {
                "modo_automatico_rega": MODO_AUTOMATICO_REGA,
                "bloqueado_por_dias": bloqueado_por_dias,
                "rega_emergencial": rega_emergencial,
                "dias_desde_ultima_rega": dias_passados,
            },
            "confianca_parametro": perfil["confianca"],
        }


    def gerar_previsao_dashboard(self, decisao: Dict[str, Any]) -> Dict[str, Any]:
        """
        Gera um payload simples no formato que o DashboardIA minimalista espera
        no tópico greenhealth/ia/previsao.
        """
        nome = decisao.get("nome") or "Planta"
        vaso = decisao.get("vaso")
        regar = decisao.get("regar") is True or decisao.get("acao") == "regar"

        seguranca = decisao.get("seguranca") or {}
        bloqueado_por_dias = seguranca.get("bloqueado_por_dias") is True
        dias_desde_ultima_rega = seguranca.get("dias_desde_ultima_rega")
        limites = decisao.get("limites_usados") or {}
        dias_entre_regas = limites.get("dias_entre_regas")

        if regar:
            previsao = "Rega recomendada agora."
        elif bloqueado_por_dias and dias_desde_ultima_rega is not None and dias_entre_regas is not None:
            try:
                restante = max(0.0, float(dias_entre_regas) - float(dias_desde_ultima_rega))
                horas = restante * 24.0
                if horas < 1:
                    previsao = "Próxima rega pode ser reavaliada em menos de 1 hora."
                elif horas < 24:
                    previsao = f"Próxima rega pode ser reavaliada em cerca de {horas:.0f} hora(s)."
                else:
                    previsao = f"Próxima rega pode ser reavaliada em cerca de {restante:.1f} dia(s)."
            except Exception:
                previsao = "Rega não recomendada agora por causa da frequência da planilha."
        else:
            previsao = "Sem rega recomendada agora. Continue monitorando."

        return {
            "tipo": "previsao_ia_greenhealth",
            "data_hora": agora_iso(),
            "vaso": vaso,
            "id_planilha": decisao.get("id_planilha"),
            "nome": nome,
            "previsao": previsao,
            "previsao_proxima_rega": previsao,
            "mensagem": previsao,
        }

    def preparar_decisao_para_dashboard(self, decisao: Dict[str, Any]) -> Dict[str, Any]:
        """
        Mantém todos os dados técnicos da decisão, mas adiciona campos resumidos
        para o DashboardIA minimalista.

        O DashboardIA atual entende principalmente:
        - greenhealth/ia/decisoes: decisão principal por planta
        - greenhealth/ia/alertas: alerta principal por planta
        - greenhealth/ia/dicas: pontos de atenção/notificações
        - greenhealth/ia/previsao: próxima ação
        """
        alertas = normalizar_lista(decisao.get("alertas"))
        dicas = normalizar_lista(decisao.get("dicas"))
        motivos_rega = normalizar_lista(decisao.get("motivos_rega"))

        pontos_atencao: List[str] = []
        for item in list(motivos_rega) + list(alertas) + list(dicas):
            texto = str(item).strip() if item is not None else ""
            if texto and texto not in pontos_atencao:
                pontos_atencao.append(texto)
            if len(pontos_atencao) >= 2:
                break

        regar = decisao.get("regar") is True or decisao.get("acao") == "regar"
        decisao_resumida = (
            "A IA recomenda regar esta planta."
            if regar
            else "A IA recomenda apenas monitorar agora."
        )

        alerta_principal = alertas[0] if alertas else "Sem alerta no momento."
        previsao = self.gerar_previsao_dashboard(decisao)["previsao"]

        if not pontos_atencao:
            pontos_atencao = [previsao]

        decisao["decisao_resumida"] = decisao_resumida
        decisao["alerta_principal"] = alerta_principal
        decisao["pontos_atencao"] = pontos_atencao[:2]
        decisao["previsao_proxima_rega"] = previsao

        # Campo genérico de notificação para logs/depuração e futuras telas.
        if regar:
            notificacao = f"{decisao.get('nome', 'Planta')}: rega recomendada agora."
            tipo_notificacao = "rega"
        elif alerta_principal != "Sem alerta no momento.":
            notificacao = f"{decisao.get('nome', 'Planta')}: {alerta_principal}"
            tipo_notificacao = "alerta"
        else:
            notificacao = f"{decisao.get('nome', 'Planta')}: monitoramento normal."
            tipo_notificacao = "monitoramento"

        decisao["notificacao"] = notificacao
        decisao["tipo_notificacao"] = tipo_notificacao

        return decisao

    def gerar_payload_alerta_dashboard(self, decisao: Dict[str, Any]) -> Dict[str, Any]:
        """
        Gera um payload próprio para greenhealth/ia/alertas.
        Mesmo sem alerta crítico, publica 'Sem alerta no momento' para manter
        o card da planta atualizado no DashboardIA.
        """
        alerta = decisao.get("alerta_principal") or "Sem alerta no momento."

        return {
            "tipo": "alerta_ia_greenhealth",
            "data_hora": agora_iso(),
            "vaso": decisao.get("vaso"),
            "id_planilha": decisao.get("id_planilha"),
            "nome": decisao.get("nome"),
            "alerta_principal": alerta,
            "alertas": [alerta],
            "mensagem": alerta,
            "notificacao": decisao.get("notificacao"),
            "tipo_notificacao": decisao.get("tipo_notificacao"),
        }

    def gerar_payload_dicas_dashboard(self, decisao: Dict[str, Any]) -> Dict[str, Any]:
        """
        Gera um payload próprio para greenhealth/ia/dicas.
        O DashboardIA usa as dicas como pontos de atenção/notificações.
        """
        pontos = normalizar_lista(decisao.get("pontos_atencao"))[:2]

        if not pontos:
            pontos = [decisao.get("previsao_proxima_rega") or "Continue monitorando esta planta."]

        return {
            "tipo": "notificacao_ia_greenhealth",
            "data_hora": agora_iso(),
            "vaso": decisao.get("vaso"),
            "id_planilha": decisao.get("id_planilha"),
            "nome": decisao.get("nome"),
            "dicas": pontos,
            "pontos_atencao": pontos,
            "mensagem": pontos[0],
            "notificacao": decisao.get("notificacao"),
            "tipo_notificacao": decisao.get("tipo_notificacao"),
        }

    def processar_payload_sensores(self, payload: Dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            print("[WARN] Payload ignorado: não é objeto JSON.")
            return

        plantas = payload.get("plantas")

        if not isinstance(plantas, list):
            print("[WARN] Payload sem array 'plantas'.")
            return

        self.base.carregar()

        for leitura in plantas:
            if not isinstance(leitura, dict):
                continue

            decisao = self.avaliar_planta(leitura, payload)
            decisao = self.preparar_decisao_para_dashboard(decisao)
            alerta_dashboard = self.gerar_payload_alerta_dashboard(decisao)
            dica_dashboard = self.gerar_payload_dicas_dashboard(decisao)
            previsao = self.gerar_previsao_dashboard(decisao)

            # Formato principal esperado pelo DashboardIA minimalista.
            self.publicar_json(TOPICO_DECISOES, decisao)

            # Sempre publica alerta e notificação/dica por planta.
            # Assim o DashboardIA atualiza os cards mesmo quando não há alerta crítico.
            self.publicar_json(TOPICO_ALERTAS, alerta_dashboard)
            self.publicar_json(TOPICO_DICAS, dica_dashboard)

            # Próxima ação/previsão mostrada no card de cada planta.
            self.publicar_json(TOPICO_PREVISAO, previsao)

            print(
                f"[IA -> DashboardIA] Vaso {decisao.get('vaso')} | "
                f"{decisao.get('nome')} | decisão: {decisao.get('acao')}"
            )
            print(f"  Decisão: {decisao.get('decisao_resumida')}")
            print(f"  Alerta: {alerta_dashboard.get('mensagem')}")
            print(f"  Notificação: {dica_dashboard.get('mensagem')}")
            print(f"  Próxima ação: {previsao.get('previsao')}")

            if decisao.get("regar") is True:
                id_vaso = valor_inteiro(decisao.get("vaso"))
                if id_vaso is None:
                    print("[WARN] Não foi possível acionar servo: vaso indefinido.")
                    continue

                permitido, motivo = self.pode_enviar_comando(id_vaso)
                if not permitido:
                    print(f"[BLOQUEADO] {motivo}")
                    continue

                if MODO_AUTOMATICO_REGA:
                    self.enviar_servo(id_vaso, int(decisao["angulo_servo"]))
                    self.registrar_rega(id_vaso)
                else:
                    print("[SIMULAÇÃO] Rega automática desligada. Nenhum servo foi acionado.")




def atualizar_payload_por_topico_individual(topico: str, texto: str) -> bool:
    """
    Atualiza o buffer interno usando tópicos individuais do mock/ESP32.

    Exemplos aceitos:
    - greenhealth/planta1/ldr -> 2887
    - greenhealth/planta1/umidade -> 936
    - greenhealth/planta1/umidade_solo -> 936
    - greenhealth/planta1/servo/angulo -> 0
    - greenhealth/sensores/temperatura -> 28.25
    - greenhealth/sensores/umidade_ar -> 83.91
    - greenhealth/sensores/data_hora -> 08/07/2026 22:50:39

    Retorna True quando conseguiu aproveitar o tópico.
    """
    global ultimo_payload_sensores, ultimo_topico_sensores

    valor_texto = texto.strip()
    agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    # Sensores gerais
    if topico == "greenhealth/sensores/temperatura":
        with ultimo_payload_lock:
            buffer_sensores_individuais["temperatura"] = valor_numero(valor_texto)
            buffer_sensores_individuais["ultima_atualizacao"] = agora
            montar_payload_individual_locked(topico)
        return True

    if topico == "greenhealth/sensores/umidade_ar":
        with ultimo_payload_lock:
            buffer_sensores_individuais["umidade_ar"] = valor_numero(valor_texto)
            buffer_sensores_individuais["ultima_atualizacao"] = agora
            montar_payload_individual_locked(topico)
        return True

    if topico == "greenhealth/sensores/data_hora":
        with ultimo_payload_lock:
            buffer_sensores_individuais["data_hora"] = valor_texto
            buffer_sensores_individuais["ultima_atualizacao"] = agora
            montar_payload_individual_locked(topico)
        return True

    # Sensores por planta
    m = re.match(r"^greenhealth/planta(\d+)/(ldr|umidade|umidade_solo|servo/angulo|servo/status)$", topico)
    if not m:
        return False

    planta_id = int(m.group(1))
    campo = m.group(2)

    with ultimo_payload_lock:
        plantas = buffer_sensores_individuais.setdefault("plantas", {})
        planta = plantas.setdefault(planta_id, {"planta": planta_id})

        if campo == "ldr":
            planta["ldr"] = valor_numero(valor_texto)
        elif campo in ["umidade", "umidade_solo"]:
            # O agente avalia o campo umidade_solo.
            planta["umidade_solo"] = valor_numero(valor_texto)
        elif campo == "servo/angulo":
            planta["angulo_servo"] = valor_numero(valor_texto)
        elif campo == "servo/status":
            planta["status_servo"] = valor_texto

        buffer_sensores_individuais["ultima_atualizacao"] = agora
        montar_payload_individual_locked(topico)

    return True


def montar_payload_individual_locked(topico_origem: str) -> None:
    """
    Monta ultimo_payload_sensores a partir do buffer individual.
    Esta função deve ser chamada com ultimo_payload_lock já adquirido.
    """
    global ultimo_payload_sensores, ultimo_topico_sensores

    plantas_dict = buffer_sensores_individuais.get("plantas", {})
    plantas_lista: List[Dict[str, Any]] = []

    for planta_id in sorted(plantas_dict.keys()):
        planta = dict(plantas_dict[planta_id])

        # Só entra na análise se tiver pelo menos ldr ou umidade_solo.
        if planta.get("ldr") is None and planta.get("umidade_solo") is None:
            continue

        plantas_lista.append(planta)

    if not plantas_lista:
        return

    data_hora = (
        buffer_sensores_individuais.get("data_hora")
        or buffer_sensores_individuais.get("ultima_atualizacao")
        or datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    )

    ultimo_payload_sensores = {
        "plantas": plantas_lista,
        "temperatura": buffer_sensores_individuais.get("temperatura"),
        "umidade_ar": buffer_sensores_individuais.get("umidade_ar"),
        "data_hora": data_hora,
        "origem": "topicos_individuais",
    }

    ultimo_topico_sensores = f"topicos_individuais/{topico_origem}"


# =========================================================
# MQTT CALLBACKS
# =========================================================

base = BaseConhecimentoPlantas()

# Para evitar erro em versões novas/antigas do paho-mqtt.
try:
    client = mqtt.Client(client_id=MQTT_CLIENT_ID, protocol=mqtt.MQTTv311)
except TypeError:
    client = mqtt.Client(client_id=MQTT_CLIENT_ID)

agente = AgenteGreenHealthIA(client, base)
encerrando = False


def on_connect(client: mqtt.Client, userdata: Any, flags: Any, rc: int) -> None:
    if rc == 0:
        print("[MQTT] Conectado com sucesso.")
        client.subscribe(TOPICO_SENSORES, qos=0)

        agente.publicar_status("online", {
            "broker": MQTT_BROKER,
            "porta": MQTT_PORT,
            "client_id": MQTT_CLIENT_ID,
            "topico_assinado": TOPICO_SENSORES,
            "topico_json_processado": TOPICO_SENSORES_JSON,
            "planilha": base.caminho,
            "modo_automatico_rega": MODO_AUTOMATICO_REGA,
        })

        print(f"[MQTT] Client ID: {MQTT_CLIENT_ID}")
        print(f"[MQTT] Assinando: {TOPICO_SENSORES}")
        print(f"[MQTT] Lendo tópicos individuais: greenhealth/planta1/..., greenhealth/planta2/..., greenhealth/planta3/...")
        print(f"[MQTT] Também aceita JSON agregado em: {TOPICO_SENSORES_JSON}")
    else:
        print(f"[MQTT] Falha ao conectar. Código: {rc}")


def on_disconnect(client: mqtt.Client, userdata: Any, rc: int) -> None:
    if not encerrando:
        print(f"[MQTT] Desconectado inesperadamente. Código: {rc}")


def on_message(client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
    global ultimo_payload_sensores, ultimo_topico_sensores

    texto = msg.payload.decode("utf-8", errors="replace")
    topico = msg.topic

    # A IA assina greenhealth/#, mas ignora mensagens da própria IA
    # e mensagens de atuadores para não entrar em loop.
    if topico.startswith("greenhealth/ia/"):
        return

    if topico.startswith("greenhealth/atuadores/"):
        return

    # 1) Primeiro tenta aproveitar tópicos individuais.
    # Ex.: greenhealth/planta1/ldr, greenhealth/planta1/umidade,
    # greenhealth/sensores/temperatura etc.
    if atualizar_payload_por_topico_individual(topico, texto):
        return

    # 2) Depois tenta JSON agregado, caso ele também exista.
    try:
        payload = json.loads(texto)
    except Exception:
        return

    if not (isinstance(payload, dict) and isinstance(payload.get("plantas"), list)):
        return

    with ultimo_payload_lock:
        ultimo_payload_sensores = payload
        ultimo_topico_sensores = topico


def loop_retorno_ia() -> None:
    """
    Publica a análise da IA a cada 5 segundos usando o último JSON recebido.
    O terminal mostra somente os retornos enviados ao DashboardIA.
    """
    while not encerrando:
        time.sleep(INTERVALO_RETORNO_IA_SEG)

        with ultimo_payload_lock:
            payload = ultimo_payload_sensores
            topico = ultimo_topico_sensores

        if payload is None:
            print("")
            print("[IA] Aguardando sensores em greenhealth/planta1/... ou JSON em greenhealth/sensores/dados...")
            continue

        print("")
        print("========== RETORNO DA IA PARA O DASHBOARDIA ==========")
        print(f"Horário: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        print(f"Último JSON recebido de: {topico}")

        try:
            agente.processar_payload_sensores(payload)
        except Exception as e:
            print(f"[ERRO] Falha ao processar payload: {e}")

        print("======================================================")

def encerrar(signum: Any = None, frame: Any = None) -> None:
    global encerrando
    encerrando = True
    print("\n[SAIR] Encerrando agente...")
    try:
        agente.publicar_status("offline")
        time.sleep(0.5)
        client.disconnect()
    except Exception:
        pass


def main() -> None:
    signal.signal(signal.SIGINT, encerrar)
    signal.signal(signal.SIGTERM, encerrar)

    print("======================================")
    print(" GreenHealth - IA externa com planilha")
    print("======================================")
    print(f"Broker MQTT: {MQTT_BROKER}:{MQTT_PORT}")
    print(f"Tópico sensores: {TOPICO_SENSORES}")
    print(f"Modo automático de rega: {MODO_AUTOMATICO_REGA}")
    print("")

    base.carregar(forcar=True)

    print("")
    print("[MAPEAMENTO VASOS -> IDS PLANILHA]")
    for vaso, id_planilha in MAPEAMENTO_VASO_PARA_ID_PLANILHA.items():
        perfil = base.obter_por_id(id_planilha)
        nome = perfil["nome"] if perfil else "NÃO ENCONTRADO"
        print(f"  Vaso {vaso} -> ID {id_planilha} -> {nome}")

    print("")

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    thread_retorno = threading.Thread(target=loop_retorno_ia, daemon=True)
    thread_retorno.start()

    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.loop_forever()


if __name__ == "__main__":
    main()
