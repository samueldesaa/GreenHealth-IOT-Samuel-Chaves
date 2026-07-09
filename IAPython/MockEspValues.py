import random
import time
import json
import re
from datetime import datetime
import paho.mqtt.client as mqtt

# ================= MQTT =================
MQTT_BROKER = "broker.emqx.io"
MQTT_PORT = 1883

MQTT_CLIENT_ID = f"mock_esp32_greenhealth_{random.randint(10000, 99999)}"

# ================= TÓPICOS =================
TOPICO_JSON = "greenhealth/sensores/dados"
TOPICO_TEMPERATURA = "greenhealth/sensores/temperatura"
TOPICO_UMIDADE_AR = "greenhealth/sensores/umidade_ar"
TOPICO_DATA_HORA = "greenhealth/sensores/data_hora"

TOPICO_COMANDO_SERVOS = "greenhealth/+/servo"

PUBLICAR_TOPICOS_INDIVIDUAIS = True
INTERVALO_ENVIO = 2

# Publicar com retain ajuda o dashboard a receber o último valor mesmo se abrir depois.
USAR_RETAIN = True
QOS_PUBLICACAO = 1

mqtt_conectado = False

# ================= PLANTAS MOCKADAS =================
plantas = {
    1: {
        "planta": 1,
        "ldr_base": 3000,
        "umidade_base": 1048,
        "pino_servo": 26,
        "angulo_servo": 0,
        "status_servo": "fechado"
    },
    2: {
        "planta": 2,
        "ldr_base": 2800,
        "umidade_base": 1350,
        "pino_servo": 27,
        "angulo_servo": 0,
        "status_servo": "fechado"
    },
    3: {
        "planta": 3,
        "ldr_base": 2400,
        "umidade_base": 1700,
        "pino_servo": 14,
        "angulo_servo": 0,
        "status_servo": "fechado"
    }
}

# ================= FUNÇÕES AUXILIARES =================
def limitar(valor, minimo=0, maximo=4095):
    return max(minimo, min(maximo, valor))


def gerar_analogico(base, variacao):
    return limitar(base + random.randint(-variacao, variacao))


def gerar_temperatura():
    return round(random.uniform(26.0, 32.5), 2)


def gerar_umidade_ar():
    return round(random.uniform(55.0, 85.0), 2)


def obter_data_hora():
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def publicar(client, topico, mensagem, retain=USAR_RETAIN):
    resultado = client.publish(
        topico,
        str(mensagem),
        qos=QOS_PUBLICACAO,
        retain=retain
    )

    resultado.wait_for_publish(timeout=2)

    if resultado.rc == mqtt.MQTT_ERR_SUCCESS:
        print(f"[OK] {topico} -> {mensagem}")
    else:
        print(f"[ERRO] {topico} -> {mensagem} | rc={resultado.rc}")


def extrair_numero_planta(topico):
    match = re.search(r"planta(\d+)", topico)

    if not match:
        return None

    return int(match.group(1))


# ================= SERVO MOCK =================
def publicar_status_servo(client, numero, status):
    plantas[numero]["status_servo"] = status
    publicar(client, f"greenhealth/planta{numero}/servo/status", status)


def publicar_angulo_servo(client, numero, angulo):
    plantas[numero]["angulo_servo"] = angulo
    publicar(client, f"greenhealth/planta{numero}/servo/angulo", angulo)


def mover_servo(client, numero, angulo):
    if numero not in plantas:
        print(f"[ERRO] Planta {numero} não existe no mock.")
        return

    angulo = max(0, min(90, int(angulo)))

    print(f"\nMovendo servo da Planta {numero} para {angulo}°")

    publicar_angulo_servo(client, numero, angulo)

    if angulo == 0:
        publicar_status_servo(client, numero, "fechado")
    elif angulo == 90:
        publicar_status_servo(client, numero, "aberto")
    else:
        publicar_status_servo(client, numero, f"angulo_{angulo}")


def ativar_irrigacao(client, numero):
    if numero not in plantas:
        print(f"[ERRO] Planta {numero} não existe no mock.")
        return

    print(f"\nAtivando irrigação da Planta {numero}")

    publicar_status_servo(client, numero, "abrindo")
    publicar_angulo_servo(client, numero, 90)

    time.sleep(1.2)

    publicar_angulo_servo(client, numero, 0)
    publicar_status_servo(client, numero, "acionado_e_fechado")


# ================= CALLBACKS MQTT =================
def on_connect(client, userdata, flags, rc):
    global mqtt_conectado

    if rc == 0:
        mqtt_conectado = True

        print("MQTT conectado com sucesso!")
        print(f"Client ID: {MQTT_CLIENT_ID}")

        client.subscribe(TOPICO_COMANDO_SERVOS, qos=1)
        print(f"Inscrito em: {TOPICO_COMANDO_SERVOS}")

    else:
        mqtt_conectado = False
        print(f"Erro ao conectar. Código: {rc}")


def on_disconnect(client, userdata, rc):
    global mqtt_conectado

    mqtt_conectado = False
    print(f"MQTT desconectado. Código: {rc}")


def on_message(client, userdata, msg):
    topico = msg.topic
    mensagem = msg.payload.decode("utf-8").strip()

    print("\n========== COMANDO RECEBIDO ==========")
    print(f"Tópico: {topico}")
    print(f"Mensagem: {mensagem}")

    if not topico.endswith("/servo"):
        print("Tópico ignorado.")
        return

    numero = extrair_numero_planta(topico)

    if numero is None:
        print("Não foi possível identificar a planta.")
        return

    comando = mensagem.lower()

    if comando in ["ativar", "regar", "1"]:
        ativar_irrigacao(client, numero)

    elif comando in ["abrir", "open"]:
        mover_servo(client, numero, 90)

    elif comando in ["fechar", "off"]:
        mover_servo(client, numero, 0)

    elif comando.isdigit():
        mover_servo(client, numero, int(comando))

    else:
        print("Comando inválido. Use: ativar, regar, abrir, fechar ou 0 a 90.")

    print("======================================\n")


# ================= PUBLICAÇÃO DOS DADOS =================
def gerar_dados_planta(planta):
    numero = planta["planta"]

    ldr = gerar_analogico(planta["ldr_base"], 180)
    umidade_solo = gerar_analogico(planta["umidade_base"], 120)

    return {
        "planta": numero,
        "ldr": ldr,
        "umidade_solo": umidade_solo,
        "pino_servo": planta["pino_servo"],
        "angulo_servo": planta["angulo_servo"]
    }


def publicar_topicos_individuais(client, dados_planta):
    numero = dados_planta["planta"]

    publicar(client, f"greenhealth/planta{numero}/ldr", dados_planta["ldr"])
    publicar(client, f"greenhealth/planta{numero}/umidade", dados_planta["umidade_solo"])
    publicar(client, f"greenhealth/planta{numero}/servo/angulo", dados_planta["angulo_servo"])
    publicar(client, f"greenhealth/planta{numero}/servo/status", plantas[numero]["status_servo"])


def publicar_ciclo(client):
    temperatura = gerar_temperatura()
    umidade_ar = gerar_umidade_ar()
    data_hora = obter_data_hora()

    lista_plantas = []

    print("\n========== ENVIANDO DADOS MOCK ==========")

    for numero in sorted(plantas.keys()):
        dados_planta = gerar_dados_planta(plantas[numero])
        lista_plantas.append(dados_planta)

        if PUBLICAR_TOPICOS_INDIVIDUAIS:
            publicar_topicos_individuais(client, dados_planta)

    payload = {
        "plantas": lista_plantas,
        "temperatura": temperatura,
        "umidade_ar": umidade_ar,
        "data_hora": data_hora
    }

    json_texto = json.dumps(payload, ensure_ascii=False)

    publicar(client, TOPICO_TEMPERATURA, temperatura)
    publicar(client, TOPICO_UMIDADE_AR, umidade_ar)
    publicar(client, TOPICO_DATA_HORA, data_hora)
    publicar(client, TOPICO_JSON, json_texto)

    print("\nJSON enviado em greenhealth/sensores/dados:")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print("=========================================\n")


# ================= PROGRAMA PRINCIPAL =================
client = mqtt.Client(client_id=MQTT_CLIENT_ID)

client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_message = on_message

print("Conectando ao broker MQTT...")
client.connect(MQTT_BROKER, MQTT_PORT, 60)

client.loop_start()

try:
    while not mqtt_conectado:
        print("Aguardando conexão MQTT...")
        time.sleep(0.5)

    while True:
        publicar_ciclo(client)
        time.sleep(INTERVALO_ENVIO)

except KeyboardInterrupt:
    print("\nMock encerrado pelo usuário.")

finally:
    client.loop_stop()
    client.disconnect()