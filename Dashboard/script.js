// ================= CONFIGURAÇÃO MQTT =================
// Usa WSS para evitar bloqueio do navegador por conteúdo inseguro.
const broker = "wss://broker.emqx.io:8084/mqtt";

const TOPICO_GERAL = "greenhealth/#";
const TOPICO_DADOS = "greenhealth/sensores/dados";
const TOPICO_TEMPERATURA = "greenhealth/sensores/temperatura";
const TOPICO_UMIDADE_AR = "greenhealth/sensores/umidade_ar";
const TOPICO_DATA_HORA = "greenhealth/sensores/data_hora";

const clientId = "site_greenhealth_dashboard_" + Math.random().toString(16).substring(2, 10);

const client = mqtt.connect(broker, {
  clientId,
  clean: true,
  connectTimeout: 6000,
  reconnectPeriod: 3000
});

// ================= ESTADO GLOBAL =================
const limitePontos = 30;
const limiteEventosIrrigacao = 30;
const maxLinhasLog = 25;

let visualizacaoPorPlanta = false;
let graficos = [];
let graficoCriado = false;

const dados = {
  labels: [],
  plantas: {},
  temperatura: [],
  umidade_ar: []
};

const dadosIrrigacao = {
  labels: [],
  plantas: {}
};

const ultimosValores = {
  plantas: {},
  temperatura: null,
  umidade_ar: null,
  data_hora: null
};

const servoValores = {};
const ultimoEventoIrrigacaoMs = {};
const linhasLog = [];

// ================= EVENTOS DA PÁGINA =================
document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("btnVisualizacao").addEventListener("click", alternarVisualizacao);
  document.getElementById("btnLimparLog").addEventListener("click", limparLog);

  atualizarCards();
  atualizarControlesServos();
  montarGraficos();
});

// ================= CONEXÃO MQTT =================
client.on("connect", () => {
  atualizarStatusMqtt("Conectado", true);

  client.subscribe(TOPICO_GERAL, (erro) => {
    if (erro) {
      registrarLog("ERRO", TOPICO_GERAL, "Falha ao assinar greenhealth/#");
      console.error("Erro ao assinar greenhealth/#:", erro);
    } else {
      registrarLog("SISTEMA", TOPICO_GERAL, "Assinado com sucesso");
    }
  });
});

client.on("reconnect", () => atualizarStatusMqtt("Reconectando...", false));
client.on("offline", () => atualizarStatusMqtt("Desconectado", false));
client.on("error", (erro) => {
  atualizarStatusMqtt("Erro na conexão", false);
  console.error("Erro MQTT:", erro);
});

client.on("message", (topic, message) => {
  const texto = message.toString();

  document.getElementById("ultimoTopico").textContent = topic;
  registrarLog("RECEBIDO", topic, texto);

  console.log("MQTT recebido:", { topic, texto });

  processarMensagemMqtt(topic, texto);
});

function atualizarStatusMqtt(texto, conectado) {
  const status = document.getElementById("mqttStatus");
  const pillTexto = document.getElementById("pillTexto");
  const dot = document.getElementById("dotConexao");

  status.textContent = texto;
  status.className = conectado ? "status online" : "status offline";
  pillTexto.textContent = conectado ? "MQTT online" : "MQTT offline";
  dot.className = conectado ? "dot online-dot" : "dot";
}

// ================= ROTEAMENTO DOS TÓPICOS =================
function processarMensagemMqtt(topic, texto) {
  if (topic === TOPICO_DADOS) {
    processarJsonPrincipal(texto);
    return;
  }

  if (topic === TOPICO_TEMPERATURA) {
    ultimosValores.temperatura = numeroOuNull(texto);
    atualizarCards();
    return;
  }

  if (topic === TOPICO_UMIDADE_AR) {
    ultimosValores.umidade_ar = numeroOuNull(texto);
    atualizarCards();
    return;
  }

  if (topic === TOPICO_DATA_HORA) {
    ultimosValores.data_hora = texto;
    document.getElementById("ultimaAtualizacao").textContent = texto;
    return;
  }

  const numeroPlanta = extrairNumeroPlantaDoTopico(topic);

  if (!numeroPlanta) {
    return;
  }

  garantirEstruturaPlanta(numeroPlanta);

  if (topic.endsWith("/ldr")) {
    processarTopicoIndividualPlanta(numeroPlanta, "ldr", texto);
    return;
  }

  if (topic.endsWith("/umidade")) {
    processarTopicoIndividualPlanta(numeroPlanta, "umidade_solo", texto);
    return;
  }

  if (topic.endsWith("/servo/status")) {
    processarStatusServo(topic, texto);
    return;
  }

  if (topic.endsWith("/servo/angulo")) {
    processarAnguloServo(topic, texto);
  }
}

function processarJsonPrincipal(texto) {
  try {
    const payload = JSON.parse(texto);

    adicionarDados(payload);
    atualizarCards();
    atualizarControlesServos();
    montarGraficos();
    atualizarGraficos();
  } catch (erro) {
    registrarLog("ERRO JSON", TOPICO_DADOS, erro.message);
    console.error("Erro ao interpretar JSON:", erro);
  }
}

function processarTopicoIndividualPlanta(numero, campo, texto) {
  const valor = numeroOuNull(texto);

  if (campo === "ldr") {
    ultimosValores.plantas[numero].ldr = converterLdrParaPorcentagem(valor);
  } else if (campo === "umidade_solo") {
    ultimosValores.plantas[numero].umidade_solo = valor;
  }

  adicionarSnapshotPorTopicoIndividual();
  atualizarCards();
  atualizarControlesServos();
  montarGraficos();
  atualizarGraficos();
}

// Cria um ponto no gráfico quando os dados chegam em tópicos separados.
function adicionarSnapshotPorTopicoIndividual() {
  const horario = ultimosValores.data_hora || new Date().toLocaleTimeString();

  dados.labels.push(horario);

  Object.keys(ultimosValores.plantas).forEach(numero => {
    garantirEstruturaPlanta(Number(numero));

    dados.plantas[numero].ldr.push(ultimosValores.plantas[numero].ldr);
    dados.plantas[numero].umidade_solo.push(ultimosValores.plantas[numero].umidade_solo);
    dados.plantas[numero].angulo_servo.push(servoValores[numero]?.angulo ?? null);
  });

  dados.temperatura.push(ultimosValores.temperatura);
  dados.umidade_ar.push(ultimosValores.umidade_ar);

  limitarHistorico();

  document.getElementById("ultimaAtualizacao").textContent = horario;
  document.getElementById("totalPlantas").textContent = Object.keys(ultimosValores.plantas).length;
}

// ================= NORMALIZAÇÃO =================
function numeroOuNull(valor) {
  if (valor === null || valor === undefined || valor === "") return null;

  const numero = Number(valor);
  return Number.isNaN(numero) ? null : numero;
}

function converterLdrParaPorcentagem(valor) {
  if (valor === null || valor === undefined) return null;

  const leitura = Number(valor);
  if (Number.isNaN(leitura)) return null;

  const percentual = (leitura / 4095) * 100;
  return Math.max(0, Math.min(100, percentual));
}

function obterPlantasDoPayload(payload) {
  if (Array.isArray(payload.plantas)) {
    return payload.plantas.map(planta => ({
      planta: Number(planta.planta),
      ldr: converterLdrParaPorcentagem(planta.ldr),
      umidade_solo: numeroOuNull(planta.umidade_solo),
      pino_servo: numeroOuNull(planta.pino_servo),
      angulo_servo: numeroOuNull(planta.angulo_servo)
    })).filter(planta => !Number.isNaN(planta.planta));
  }

  // Compatibilidade com formato antigo: solo1, solo2, ldr1, ldr2...
  const plantasAntigas = [];

  for (let numero = 1; numero <= 10; numero++) {
    const solo = payload[`solo${numero}`];
    const ldr = payload[`ldr${numero}`];

    if (solo !== undefined || ldr !== undefined) {
      plantasAntigas.push({
        planta: numero,
        ldr: converterLdrParaPorcentagem(ldr),
        umidade_solo: solo !== undefined ? Number(solo) : null,
        pino_servo: null,
        angulo_servo: null
      });
    }
  }

  return plantasAntigas;
}

function garantirEstruturaPlanta(numero) {
  if (!dados.plantas[numero]) {
    dados.plantas[numero] = {
      ldr: Array(Math.max(dados.labels.length - 1, 0)).fill(null),
      umidade_solo: Array(Math.max(dados.labels.length - 1, 0)).fill(null),
      angulo_servo: Array(Math.max(dados.labels.length - 1, 0)).fill(null)
    };
  }

  if (!ultimosValores.plantas[numero]) {
    ultimosValores.plantas[numero] = {
      ldr: null,
      umidade_solo: null,
      pino_servo: null,
      angulo_servo: null
    };
  }

  garantirServoPlanta(numero);
}

function garantirServoPlanta(numero) {
  if (!servoValores[numero]) {
    servoValores[numero] = {
      angulo: 0,
      status: "Aguardando status",
      ultimoEnvio: "Nenhum comando enviado"
    };
  }
}

// ================= DADOS DO JSON PRINCIPAL =================
function adicionarDados(payload) {
  const horario = payload.data_hora || ultimosValores.data_hora || new Date().toLocaleTimeString();
  const plantasRecebidas = obterPlantasDoPayload(payload);
  const idsRecebidos = new Set(plantasRecebidas.map(planta => planta.planta));

  dados.labels.push(horario);

  Object.keys(dados.plantas).forEach(numero => {
    if (!idsRecebidos.has(Number(numero))) {
      dados.plantas[numero].ldr.push(null);
      dados.plantas[numero].umidade_solo.push(null);
      dados.plantas[numero].angulo_servo.push(null);
    }
  });

  plantasRecebidas.forEach(planta => {
    garantirEstruturaPlanta(planta.planta);

    dados.plantas[planta.planta].ldr.push(planta.ldr);
    dados.plantas[planta.planta].umidade_solo.push(planta.umidade_solo);

    if (planta.angulo_servo !== null && !Number.isNaN(planta.angulo_servo)) {
      dados.plantas[planta.planta].angulo_servo.push(planta.angulo_servo);
      ultimosValores.plantas[planta.planta].angulo_servo = planta.angulo_servo;
      servoValores[planta.planta].angulo = planta.angulo_servo;
    } else {
      dados.plantas[planta.planta].angulo_servo.push(servoValores[planta.planta].angulo ?? null);
    }

    ultimosValores.plantas[planta.planta].ldr = planta.ldr;
    ultimosValores.plantas[planta.planta].umidade_solo = planta.umidade_solo;

    if (planta.pino_servo !== null && !Number.isNaN(planta.pino_servo)) {
      ultimosValores.plantas[planta.planta].pino_servo = planta.pino_servo;
    }
  });

  dados.temperatura.push(numeroOuNull(payload.temperatura));
  dados.umidade_ar.push(numeroOuNull(payload.umidade_ar));

  ultimosValores.temperatura = numeroOuNull(payload.temperatura);
  ultimosValores.umidade_ar = numeroOuNull(payload.umidade_ar);
  ultimosValores.data_hora = horario;

  limitarHistorico();

  document.getElementById("ultimaAtualizacao").textContent = horario;
  document.getElementById("totalPlantas").textContent = Object.keys(ultimosValores.plantas).length;
}

function limitarHistorico() {
  while (dados.labels.length > limitePontos) {
    dados.labels.shift();
    dados.temperatura.shift();
    dados.umidade_ar.shift();

    Object.values(dados.plantas).forEach(planta => {
      planta.ldr.shift();
      planta.umidade_solo.shift();
      planta.angulo_servo.shift();
    });
  }
}

// ================= CARDS =================
function atualizarCards() {
  const areaCards = document.getElementById("cards");
  const numeros = Object.keys(ultimosValores.plantas).map(Number).sort((a, b) => a - b);

  let html = "";

  numeros.forEach(numero => {
    const planta = ultimosValores.plantas[numero];
    const servo = servoValores[numero];

    html += `
      <div class="card glass">
        <span>Planta ${numero} • Umidade do solo</span>
        <strong>${formatarValor(planta.umidade_solo)}</strong>
        <small>Leitura analógica</small>
      </div>

      <div class="card glass">
        <span>Planta ${numero} • Luminosidade LDR</span>
        <strong>${formatarPorcentagem(planta.ldr)}</strong>
        <small>Convertido de 0 a 4095 para 0 a 100%</small>
      </div>

      <div class="card glass">
        <span>Planta ${numero} • Servo</span>
        <strong>${servo ? servo.angulo + "°" : "--"}</strong>
        <small>
          Pino: ${planta.pino_servo !== null ? "GPIO " + planta.pino_servo : "não informado"}<br>
          Status: ${servo ? servo.status : "aguardando"}
        </small>
      </div>
    `;
  });

  html += `
    <div class="card glass">
      <span>Temperatura</span>
      <strong>${ultimosValores.temperatura !== null ? ultimosValores.temperatura.toFixed(1) + " °C" : "--"}</strong>
      <small>DHT11/DHT22</small>
    </div>

    <div class="card glass">
      <span>Umidade do ar</span>
      <strong>${ultimosValores.umidade_ar !== null ? ultimosValores.umidade_ar.toFixed(1) + " %" : "--"}</strong>
      <small>DHT11/DHT22</small>
    </div>
  `;

  if (numeros.length === 0) {
    html = `
      <div class="empty glass">
        Aguardando mensagens MQTT em greenhealth/#...<br>
        A página aceita JSON geral e também tópicos individuais por planta.
      </div>
    ` + html;
  }

  areaCards.innerHTML = html;
}

function formatarValor(valor) {
  return valor !== null && valor !== undefined && !Number.isNaN(valor) ? valor : "--";
}

function formatarPorcentagem(valor) {
  return valor !== null && valor !== undefined && !Number.isNaN(valor) ? valor.toFixed(0) + " %" : "--";
}

// ================= CONTROLES DOS SERVOS =================
function atualizarControlesServos() {
  const area = document.getElementById("controlesServos");
  const numeros = Object.keys(ultimosValores.plantas).map(Number).sort((a, b) => a - b);

  if (numeros.length === 0) {
    area.innerHTML = `
      <div class="empty glass">
        Aguardando plantas no MQTT para gerar os controles dos servos...
      </div>
    `;
    return;
  }

  let html = "";

  numeros.forEach(numero => {
    garantirServoPlanta(numero);

    const planta = ultimosValores.plantas[numero];
    const servo = servoValores[numero];

    const anguloAtual = servo.angulo !== null && servo.angulo !== undefined ? Number(servo.angulo) : 0;
    const anguloLimitado = Math.max(0, Math.min(90, anguloAtual));

    html += `
      <div class="servo-card">
        <h3>Planta ${numero}</h3>

        <div class="servo-info">
          Servo: ${planta.pino_servo !== null ? "GPIO " + planta.pino_servo : "pino não informado"}<br>
          Tópico: greenhealth/planta${numero}/servo
        </div>

        <div class="range-row">
          <input type="range" min="0" max="90" value="${anguloLimitado}" data-servo-range="${numero}">
          <div class="servo-value" id="servoValor${numero}">${anguloLimitado}°</div>
        </div>

        <div class="servo-buttons">
          <button type="button" data-enviar-servo="${numero}">Enviar ângulo</button>
          <button type="button" class="btn-secondary" data-ativar-servo="${numero}">Ativar irrigação</button>
        </div>

        <div class="servo-status">
          Status: ${servo.status}<br>
          Último envio: ${servo.ultimoEnvio}
        </div>
      </div>
    `;
  });

  area.innerHTML = html;

  document.querySelectorAll("[data-servo-range]").forEach(range => {
    range.addEventListener("input", () => {
      const numero = range.dataset.servoRange;
      const valor = document.getElementById(`servoValor${numero}`);
      if (valor) valor.textContent = `${range.value}°`;
    });
  });

  document.querySelectorAll("[data-enviar-servo]").forEach(botao => {
    botao.addEventListener("click", () => enviarAnguloServo(Number(botao.dataset.enviarServo)));
  });

  document.querySelectorAll("[data-ativar-servo]").forEach(botao => {
    botao.addEventListener("click", () => ativarIrrigacao(Number(botao.dataset.ativarServo)));
  });
}

function enviarAnguloServo(numero) {
  const range = document.querySelector(`[data-servo-range="${numero}"]`);
  if (!range) return;

  const angulo = Math.max(0, Math.min(90, Number(range.value)));
  const topicoComando = `greenhealth/planta${numero}/servo`;

  client.publish(topicoComando, String(angulo));
  registrarLog("ENVIADO", topicoComando, String(angulo));

  garantirServoPlanta(numero);

  servoValores[numero].angulo = angulo;
  servoValores[numero].ultimoEnvio = `${angulo}° enviado às ${new Date().toLocaleTimeString()}`;

  atualizarCards();
  atualizarControlesServos();
}

function ativarIrrigacao(numero) {
  const topicoComando = `greenhealth/planta${numero}/servo`;

  client.publish(topicoComando, "ativar");
  registrarLog("ENVIADO", topicoComando, "ativar");

  garantirServoPlanta(numero);

  servoValores[numero].ultimoEnvio = `ativar enviado às ${new Date().toLocaleTimeString()}`;

  atualizarCards();
  atualizarControlesServos();
}

// ================= STATUS DOS SERVOS =================
function extrairNumeroPlantaDoTopico(topico) {
  const match = topico.match(/planta(\d+)/);
  if (!match) return null;
  return Number(match[1]);
}

function processarStatusServo(topico, mensagem) {
  const numero = extrairNumeroPlantaDoTopico(topico);
  if (!numero) return;

  garantirServoPlanta(numero);

  servoValores[numero].status = mensagem;

  const status = mensagem.toLowerCase();

  if (
    status.includes("abrindo") ||
    status.includes("acionado") ||
    status.includes("ativado") ||
    status.includes("irrig")
  ) {
    registrarEventoIrrigacao(numero, mensagem);
  }

  atualizarCards();
  atualizarControlesServos();
  montarGraficos();
  atualizarGraficos();
}

function processarAnguloServo(topico, mensagem) {
  const numero = extrairNumeroPlantaDoTopico(topico);
  if (!numero) return;

  const angulo = Number(mensagem);
  if (Number.isNaN(angulo)) return;

  garantirServoPlanta(numero);
  garantirEstruturaPlanta(numero);

  servoValores[numero].angulo = angulo;
  ultimosValores.plantas[numero].angulo_servo = angulo;

  atualizarCards();
  atualizarControlesServos();
}

function garantirEstruturaIrrigacao(numero) {
  if (!dadosIrrigacao.plantas[numero]) {
    dadosIrrigacao.plantas[numero] = Array(dadosIrrigacao.labels.length).fill(0);
  }
}

function registrarEventoIrrigacao(numero, status) {
  const agoraMs = Date.now();

  if (ultimoEventoIrrigacaoMs[numero] && agoraMs - ultimoEventoIrrigacaoMs[numero] < 3000) {
    return;
  }

  ultimoEventoIrrigacaoMs[numero] = agoraMs;

  garantirEstruturaIrrigacao(numero);

  const horario = new Date().toLocaleTimeString();

  dadosIrrigacao.labels.push(horario);

  Object.keys(dadosIrrigacao.plantas).forEach(plantaNumero => {
    dadosIrrigacao.plantas[plantaNumero].push(0);
  });

  dadosIrrigacao.plantas[numero][dadosIrrigacao.plantas[numero].length - 1] = 1;

  limitarHistoricoIrrigacao();

  document.getElementById("ultimaIrrigacao").textContent =
    `Planta ${numero} às ${horario} (${status})`;
}

function limitarHistoricoIrrigacao() {
  while (dadosIrrigacao.labels.length > limiteEventosIrrigacao) {
    dadosIrrigacao.labels.shift();

    Object.values(dadosIrrigacao.plantas).forEach(planta => {
      planta.shift();
    });
  }
}

// ================= GRÁFICOS =================
function alternarVisualizacao() {
  visualizacaoPorPlanta = !visualizacaoPorPlanta;

  const botao = document.getElementById("btnVisualizacao");
  botao.textContent = visualizacaoPorPlanta ? "Visualizar por tipo de sensor" : "Visualizar por planta";

  montarGraficos();
}

function limparGraficos() {
  graficos.forEach(grafico => grafico.destroy());
  graficos = [];
  document.getElementById("areaGraficos").innerHTML = "";
}

function criarBoxGrafico(titulo, idCanvas) {
  const area = document.getElementById("areaGraficos");

  const box = document.createElement("div");
  box.className = "chart-box glass";

  const h2 = document.createElement("h2");
  h2.textContent = titulo;

  const canvas = document.createElement("canvas");
  canvas.id = idCanvas;

  box.appendChild(h2);
  box.appendChild(canvas);
  area.appendChild(box);
}

function montarGraficos() {
  limparGraficos();

  const numeros = Object.keys(dados.plantas).map(Number).sort((a, b) => a - b);

  if (numeros.length === 0) {
    criarBoxGrafico("Aguardando dados das plantas", "graficoVazio");
    graficos.push(criarGrafico("graficoVazio", [criarDataset("Sem dados", [])]));
    return;
  }

  if (visualizacaoPorPlanta) {
    numeros.forEach(numero => {
      criarBoxGrafico(`Planta ${numero} - Umidade, Luminosidade e Servo`, `graficoPlanta${numero}`);

      graficos.push(criarGrafico(`graficoPlanta${numero}`, [
        criarDataset(`Planta ${numero} • Umidade do solo`, dados.plantas[numero].umidade_solo),
        criarDataset(`Planta ${numero} • LDR %`, dados.plantas[numero].ldr),
        criarDataset(`Planta ${numero} • Ângulo servo`, dados.plantas[numero].angulo_servo)
      ], null, dados.labels, "line"));
    });

    criarBoxGrafico("DHT - Temperatura e Umidade do Ar", "graficoDHT");
    graficos.push(criarGrafico("graficoDHT", [
      criarDataset("Temperatura °C", dados.temperatura),
      criarDataset("Umidade do ar %", dados.umidade_ar)
    ], null, dados.labels, "line"));
  } else {
    criarBoxGrafico("Sensores de Umidade do Solo", "graficoSolo");
    criarBoxGrafico("Sensores de Luminosidade LDR (%)", "graficoLDR");
    criarBoxGrafico("Ângulo dos Servos", "graficoServoAngulo");
    criarBoxGrafico("DHT - Temperatura e Umidade do Ar", "graficoDHT");

    graficos.push(criarGrafico("graficoSolo", numeros.map(numero =>
      criarDataset(`Planta ${numero} • Umidade do solo`, dados.plantas[numero].umidade_solo)
    ), null, dados.labels, "line"));

    graficos.push(criarGrafico("graficoLDR", numeros.map(numero =>
      criarDataset(`Planta ${numero} • LDR %`, dados.plantas[numero].ldr)
    ), 100, dados.labels, "line"));

    graficos.push(criarGrafico("graficoServoAngulo", numeros.map(numero =>
      criarDataset(`Planta ${numero} • Servo °`, dados.plantas[numero].angulo_servo)
    ), 90, dados.labels, "line"));

    graficos.push(criarGrafico("graficoDHT", [
      criarDataset("Temperatura °C", dados.temperatura),
      criarDataset("Umidade do ar %", dados.umidade_ar)
    ], null, dados.labels, "line"));
  }

  criarBoxGrafico("Histórico de Ativação da Irrigação", "graficoIrrigacao");

  const numerosIrrigacao = Object.keys(dadosIrrigacao.plantas).map(Number).sort((a, b) => a - b);

  if (numerosIrrigacao.length === 0) {
    graficos.push(criarGrafico("graficoIrrigacao", [criarDataset("Aguardando ativações", [])], 1, dadosIrrigacao.labels, "bar"));
  } else {
    graficos.push(criarGrafico("graficoIrrigacao", numerosIrrigacao.map(numero =>
      criarDataset(`Planta ${numero} • irrigação ativada`, dadosIrrigacao.plantas[numero])
    ), 1, dadosIrrigacao.labels, "bar"));
  }
}

function criarDataset(label, data) {
  return {
    label,
    data,
    borderWidth: 2,
    tension: 0.35,
    fill: false,
    pointRadius: 3,
    pointHoverRadius: 6
  };
}

function criarGrafico(idCanvas, datasets, maximoY = null, labels = dados.labels, tipo = "line") {
  const ctx = document.getElementById(idCanvas).getContext("2d");

  return new Chart(ctx, {
    type: tipo,
    data: {
      labels,
      datasets
    },
    options: {
      responsive: true,
      animation: false,
      maintainAspectRatio: false,
      interaction: {
        mode: "index",
        intersect: false
      },
      plugins: {
        legend: {
          position: "top",
          labels: {
            color: "rgba(239, 255, 248, 0.86)",
            usePointStyle: true,
            boxWidth: 8,
            padding: 18
          }
        },
        tooltip: {
          backgroundColor: "rgba(6, 29, 47, 0.92)",
          borderColor: "rgba(255, 255, 255, 0.22)",
          borderWidth: 1,
          titleColor: "#ffffff",
          bodyColor: "#effff8"
        }
      },
      scales: {
        y: {
          beginAtZero: true,
          max: maximoY,
          grid: {
            color: "rgba(255, 255, 255, 0.11)"
          },
          ticks: {
            color: "rgba(239, 255, 248, 0.72)",
            stepSize: tipo === "bar" ? 1 : undefined
          }
        },
        x: {
          grid: {
            color: "rgba(255, 255, 255, 0.08)"
          },
          ticks: {
            color: "rgba(239, 255, 248, 0.72)",
            maxRotation: 45
          }
        }
      }
    }
  });
}

function atualizarGraficos() {
  graficos.forEach(grafico => grafico.update());
}

// ================= LOG MQTT =================
function registrarLog(tipo, topico, mensagem) {
  const horario = new Date().toLocaleTimeString();
  const textoMensagem = typeof mensagem === "string" ? mensagem : JSON.stringify(mensagem);
  const linha = `[${horario}] ${tipo}\nTópico: ${topico}\nMensagem: ${textoMensagem}\n`;

  linhasLog.unshift(linha);

  while (linhasLog.length > maxLinhasLog) {
    linhasLog.pop();
  }

  const log = document.getElementById("mqttLog");
  if (log) {
    log.textContent = linhasLog.join("\n");
  }
}

function limparLog() {
  linhasLog.length = 0;
  document.getElementById("mqttLog").textContent = "Log limpo. Aguardando novas mensagens...";
}
