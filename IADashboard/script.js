// script.js
// GreenHealth - Dashboard IA minimalista
// Foco: últimas decisões por planta, recomendações principais e alertas simples.

// ================= CONFIGURAÇÃO MQTT =================

const broker = "wss://broker.emqx.io:8084/mqtt";

const TOPICO_GERAL_IA = "greenhealth/ia/#";
const TOPICO_STATUS = "greenhealth/ia/status";
const TOPICO_DECISOES = "greenhealth/ia/decisoes";
const TOPICO_ALERTAS = "greenhealth/ia/alertas";
const TOPICO_DICAS = "greenhealth/ia/dicas";
const TOPICO_PREVISAO = "greenhealth/ia/previsao";

const clientId =
  "site_greenhealth_ia_minimal_" +
  Math.random().toString(16).substring(2, 10);

const client = mqtt.connect(broker, {
  clientId,
  clean: true,
  connectTimeout: 6000,
  reconnectPeriod: 3000
});

// ================= ESTADO =================

const estado = {
  conectado: false,
  plantas: {},
  ultimasMensagens: []
};

// ================= INICIALIZAÇÃO =================

document.addEventListener("DOMContentLoaded", () => {
  prepararTelaMinimalista();
  renderizarTudo();

  const connectBtn = document.getElementById("connectBtn");
  const disconnectBtn = document.getElementById("disconnectBtn");

  if (connectBtn) {
    connectBtn.addEventListener("click", reconectarMqtt);
  }

  if (disconnectBtn) {
    disconnectBtn.addEventListener("click", desconectarMqtt);
  }
});

// ================= CONEXÃO MQTT =================

client.on("connect", () => {
  estado.conectado = true;

  atualizarStatusMqtt(
    "Conectado",
    true,
    "IA conectada ao MQTT."
  );

  client.subscribe(TOPICO_GERAL_IA, (erro) => {
    if (erro) {
      console.error("Erro ao assinar greenhealth/ia/#:", erro);
      atualizarStatusMqtt(
        "Erro",
        false,
        "Falha ao assinar tópicos da IA."
      );
      return;
    }

    console.log("Assinado:", TOPICO_GERAL_IA);
  });
});

client.on("reconnect", () => {
  estado.conectado = false;

  atualizarStatusMqtt(
    "Reconectando...",
    false,
    "Tentando reconectar ao MQTT..."
  );
});

client.on("offline", () => {
  estado.conectado = false;

  atualizarStatusMqtt(
    "Desconectado",
    false,
    "Cliente MQTT offline."
  );
});

client.on("close", () => {
  estado.conectado = false;

  atualizarStatusMqtt(
    "Desconectado",
    false,
    "Conexão MQTT fechada."
  );
});

client.on("error", (erro) => {
  estado.conectado = false;

  atualizarStatusMqtt(
    "Erro",
    false,
    "Erro na conexão MQTT."
  );

  console.error("Erro MQTT:", erro);
});

client.on("message", (topic, message) => {
  const texto = message.toString();
  const payload = interpretarPayload(texto);

  console.log("MQTT IA recebido:", { topic, texto });

  processarMensagem(topic, payload);
});

// ================= PROCESSAMENTO =================

function processarMensagem(topic, payload) {
  if (topic === TOPICO_STATUS) {
    processarStatusIA(payload);
    return;
  }

  if (topic === TOPICO_DECISOES) {
    processarDecisao(payload);
    return;
  }

  if (topic === TOPICO_ALERTAS) {
    processarAlerta(payload);
    return;
  }

  if (topic === TOPICO_DICAS) {
    processarDica(payload);
    return;
  }

  if (topic === TOPICO_PREVISAO) {
    processarPrevisao(payload);
    return;
  }
}

function processarStatusIA(payload) {
  const status = payload.status || "online";

  estado.ultimasMensagens.unshift({
    tipo: "status",
    texto: `Agente IA ${status}`,
    data: payload.data_hora || new Date().toISOString()
  });

  estado.ultimasMensagens = estado.ultimasMensagens.slice(0, 5);
}

function processarDecisao(payload) {
  const planta = obterOuCriarPlanta(payload);

  planta.ultimaDecisao = payload;
  planta.nome = payload.nome || planta.nome;
  planta.atualizadaEm = payload.data_hora || new Date().toISOString();

  const deveRegar = payload.regar === true || payload.acao === "regar";

  planta.status = deveRegar ? "regar" : "monitorar";

  planta.decisaoTexto = deveRegar
    ? "A IA recomenda regar esta planta."
    : "A IA recomenda apenas monitorar agora.";

  const motivos = [
    ...normalizarArray(payload.motivos_rega),
    ...normalizarArray(payload.dicas)
  ];

  motivos.forEach((item) => adicionarPontoAtencao(planta, item));

  const alertas = normalizarArray(payload.alertas);

  if (alertas.length > 0) {
    planta.alertaPrincipal = alertas[0];
  }

  renderizarTudo();
}

function processarAlerta(payload) {
  const planta = obterOuCriarPlanta(payload);

  planta.nome = payload.nome || planta.nome;
  planta.atualizadaEm = payload.data_hora || new Date().toISOString();

  const alertas = normalizarArray(payload.alertas);

  if (alertas.length === 0 && payload.mensagem) {
    alertas.push(payload.mensagem);
  }

  if (alertas.length > 0) {
    planta.alertaPrincipal = alertas[0];
    adicionarPontoAtencao(planta, alertas[0]);
  }

  renderizarTudo();
}

function processarDica(payload) {
  const planta = obterOuCriarPlanta(payload);

  planta.nome = payload.nome || planta.nome;
  planta.atualizadaEm = payload.data_hora || new Date().toISOString();

  const dicas = normalizarArray(payload.dicas);

  if (dicas.length === 0 && payload.mensagem) {
    dicas.push(payload.mensagem);
  }

  dicas.forEach((dica) => adicionarPontoAtencao(planta, dica));

  renderizarTudo();
}

function processarPrevisao(payload) {
  const planta = obterOuCriarPlanta(payload);

  planta.nome = payload.nome || planta.nome;
  planta.atualizadaEm = payload.data_hora || new Date().toISOString();

  planta.previsao =
    payload.previsao_proxima_rega ||
    payload.previsao ||
    payload.motivo ||
    payload.mensagem ||
    "Sem previsão definida.";

  renderizarTudo();
}

// ================= ESTADO POR PLANTA =================

function obterOuCriarPlanta(payload) {
  const chave = obterChavePlanta(payload);

  if (!estado.plantas[chave]) {
    estado.plantas[chave] = {
      chave,
      vaso:
        payload.vaso ??
        payload.planta ??
        payload.id_planta ??
        payload.id_planilha ??
        chave,
      nome: payload.nome || `Planta ${chave}`,
      status: "monitorar",
      decisaoTexto: "Aguardando decisão da IA.",
      previsao: "Aguardando previsão.",
      alertaPrincipal: "Sem alerta no momento.",
      pontosAtencao: [],
      atualizadaEm: new Date().toISOString()
    };
  }

  return estado.plantas[chave];
}

function obterChavePlanta(payload) {
  return String(
    payload.vaso ??
    payload.planta ??
    payload.id_planta ??
    payload.id_planilha ??
    payload.nome ??
    "geral"
  );
}

function adicionarPontoAtencao(planta, texto) {
  if (!texto) return;

  const valor = String(texto).trim();

  if (!valor) return;

  const jaExiste = planta.pontosAtencao.some((item) => item === valor);

  if (!jaExiste) {
    planta.pontosAtencao.unshift(valor);
  }

  planta.pontosAtencao = planta.pontosAtencao.slice(0, 2);
}

// ================= RENDERIZAÇÃO =================

function renderizarTudo() {
  atualizarContadoresMinimalistas();
  renderizarRecomendacoesPrincipais();
  renderizarPlantasMinimalistas();
}

function renderizarRecomendacoesPrincipais() {
  const container = document.getElementById("mainRecommendations");

  if (!container) return;

  const plantas = obterPlantasOrdenadas();

  if (plantas.length === 0) {
    container.innerHTML = `
      <div class="empty">
        Aguardando decisões da IA...
      </div>
    `;
    return;
  }

  const cards = [];

  plantas.forEach((planta) => {
    if (planta.status === "regar") {
      cards.push({
        classe: "water",
        etiqueta: "Rega",
        titulo: `${planta.nome} precisa de água`,
        detalhe: planta.previsao || "A IA recomenda regar esta planta."
      });
    }

    if (
      planta.alertaPrincipal &&
      planta.alertaPrincipal !== "Sem alerta no momento."
    ) {
      cards.push({
        classe: detectarClasseAlerta(planta.alertaPrincipal),
        etiqueta: "Alerta",
        titulo: `${planta.nome}: ${planta.alertaPrincipal}`,
        detalhe: "Verifique esta planta primeiro."
      });
    }

    if (planta.previsao && planta.previsao !== "Aguardando previsão.") {
      cards.push({
        classe: "warning",
        etiqueta: "Previsão",
        titulo: `${planta.nome}`,
        detalhe: planta.previsao
      });
    }
  });

  const cardsFinais = cards.slice(0, 3);

  if (cardsFinais.length === 0) {
    container.innerHTML = `
      <div class="empty">
        Nenhuma ação urgente no momento.
      </div>
    `;
    return;
  }

  container.innerHTML = cardsFinais
    .map(
      (card) => `
        <article class="ia-big-card ${card.classe}">
          <span>${escaparHtml(card.etiqueta)}</span>
          <strong>${escaparHtml(card.titulo)}</strong>
          <small>${escaparHtml(card.detalhe)}</small>
        </article>
      `
    )
    .join("");
}

function renderizarPlantasMinimalistas() {
  const container = document.getElementById("plantInsights");

  if (!container) return;

  const plantas = obterPlantasOrdenadas();

  if (plantas.length === 0) {
    container.innerHTML = `
      <div class="empty">
        Aguardando decisões da IA por planta...
      </div>
    `;
    return;
  }

  container.innerHTML = plantas
    .map((planta) => {
      const statusClasse = planta.status === "regar" ? "water" : "monitor";
      const statusTexto = planta.status === "regar" ? "Regar" : "Monitorar";

      const pontos = planta.pontosAtencao.slice(0, 2);

      return `
        <article class="ia-plant-card glass">
          <div class="ia-plant-header">
            <div>
              <h3>${escaparHtml(planta.nome)}</h3>
              <p>Vaso ${escaparHtml(planta.vaso)}</p>
            </div>

            <span class="ia-plant-status ${statusClasse}">
              ${statusTexto}
            </span>
          </div>

          <div class="ia-minimal-decision">
            <span>Última decisão</span>
            <strong>${escaparHtml(planta.decisaoTexto)}</strong>
          </div>

          <div class="ia-minimal-block">
            <span>Próxima ação</span>
            <p>${escaparHtml(planta.previsao)}</p>
          </div>

          <div class="ia-minimal-block">
            <span>Prestar atenção</span>
            ${
              pontos.length > 0
                ? `
                  <ul>
                    ${pontos
                      .map((ponto) => `<li>${escaparHtml(ponto)}</li>`)
                      .join("")}
                  </ul>
                `
                : `<p>Nenhum ponto crítico no momento.</p>`
            }
          </div>

          <div class="ia-alerta-planta">
            <span>Alerta</span>
            <p>${escaparHtml(planta.alertaPrincipal)}</p>
          </div>
        </article>
      `;
    })
    .join("");
}

function atualizarContadoresMinimalistas() {
  const plantas = obterPlantasOrdenadas();

  const totalAlertas = plantas.filter(
    (planta) =>
      planta.alertaPrincipal &&
      planta.alertaPrincipal !== "Sem alerta no momento."
  ).length;

  const totalRegas = plantas.filter((planta) => planta.status === "regar").length;

  const countAlertas = document.getElementById("countAlertas");
  const countDicas = document.getElementById("countDicas");
  const countDecisoes = document.getElementById("countDecisoes");
  const countRegas = document.getElementById("countRegas");

  if (countAlertas) countAlertas.textContent = totalAlertas;
  if (countDicas) countDicas.textContent = plantas.length;
  if (countDecisoes) countDecisoes.textContent = plantas.length;
  if (countRegas) countRegas.textContent = totalRegas;
}

function prepararTelaMinimalista() {
  esconderSecoesAntigas();

  trocarTextoDosCardsSuperiores();
}

function esconderSecoesAntigas() {
  const idsParaEsconder = [
    "decisionCard",
    "decisionEmpty",
    "feed",
    "alertsList",
    "tipsList",
    "forecastList",
    "mqttLog"
  ];

  idsParaEsconder.forEach((id) => {
    const elemento = document.getElementById(id);

    if (elemento) {
      const section = elemento.closest("section");

      if (section) {
        section.style.display = "none";
      } else {
        elemento.style.display = "none";
      }
    }
  });

  const titulosParaEsconder = [
    "Última decisão da IA",
    "Notificações recebidas",
    "Alertas da IA",
    "Dicas inteligentes",
    "Previsão de rega",
    "Tópicos MQTT monitorados"
  ];

  document.querySelectorAll("h2, h3").forEach((titulo) => {
    const texto = titulo.textContent.trim();

    if (titulosParaEsconder.includes(texto)) {
      const section = titulo.closest("section");

      if (section) {
        section.style.display = "none";
      }
    }
  });
}

function trocarTextoDosCardsSuperiores() {
  const cards = document.querySelectorAll(".cards .card");

  if (cards[0]) {
    cards[0].querySelector("span").textContent = "Plantas com alerta";
    cards[0].querySelector("small").textContent = "Precisam de atenção.";
  }

  if (cards[1]) {
    cards[1].querySelector("span").textContent = "Plantas monitoradas";
    cards[1].querySelector("small").textContent = "Com dados da IA.";
  }

  if (cards[2]) {
    cards[2].querySelector("span").textContent = "Decisões recentes";
    cards[2].querySelector("small").textContent = "Uma por planta.";
  }

  if (cards[3]) {
    cards[3].querySelector("span").textContent = "Regas indicadas";
    cards[3].querySelector("small").textContent = "Recomendadas agora.";
  }
}

// ================= UTILITÁRIOS =================

function obterPlantasOrdenadas() {
  return Object.values(estado.plantas).sort((a, b) => {
    const na = Number(a.vaso);
    const nb = Number(b.vaso);

    if (Number.isNaN(na) || Number.isNaN(nb)) {
      return String(a.vaso).localeCompare(String(b.vaso));
    }

    return na - nb;
  });
}

function interpretarPayload(texto) {
  try {
    return JSON.parse(texto);
  } catch {
    return {
      mensagem: texto
    };
  }
}

function normalizarArray(valor) {
  if (!valor) return [];

  if (Array.isArray(valor)) {
    return valor;
  }

  return [String(valor)];
}

function detectarClasseAlerta(texto) {
  const t = String(texto).toLowerCase();

  if (
    t.includes("excesso") ||
    t.includes("risco") ||
    t.includes("muito") ||
    t.includes("crítico") ||
    t.includes("critico")
  ) {
    return "alert";
  }

  return "warning";
}

function atualizarStatusMqtt(texto, conectado, detalhe) {
  const statusText = document.getElementById("statusText");
  const statusDetail = document.getElementById("statusDetail");
  const statusDot = document.getElementById("statusDot");

  if (statusText) {
    statusText.textContent = texto;
  }

  if (statusDetail) {
    statusDetail.textContent = detalhe || texto;
    statusDetail.className = conectado ? "status online" : "status offline";
  }

  if (statusDot) {
    statusDot.className = conectado ? "dot online-dot" : "dot";
  }
}

function reconectarMqtt() {
  if (client.connected) {
    atualizarStatusMqtt(
      "Conectado",
      true,
      "A IA já está conectada ao MQTT."
    );
    return;
  }

  atualizarStatusMqtt(
    "Reconectando...",
    false,
    "Tentando reconectar ao MQTT..."
  );

  client.reconnect();
}

function desconectarMqtt() {
  if (!client.connected) {
    atualizarStatusMqtt(
      "Desconectado",
      false,
      "Cliente MQTT já está desconectado."
    );
    return;
  }

  client.end(false, () => {
    atualizarStatusMqtt(
      "Desconectado",
      false,
      "Conexão encerrada manualmente."
    );
  });
}

function escaparHtml(valor) {
  return String(valor)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}