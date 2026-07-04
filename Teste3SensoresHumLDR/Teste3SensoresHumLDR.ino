#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include "DHT.h"
#include "RTClib.h"

// ================= WIFI =================
const char* WIFI_SSID = "S20FE";
const char* WIFI_PASSWORD = "samuelsa";

// ================= MQTT =================
const char* MQTT_BROKER = "broker.emqx.io";
const int MQTT_PORT = 1883;

const char* MQTT_CLIENT_ID = "esp32_greenhealth_samuel_001";

// ================= TÓPICOS GERAIS =================
const char* TOPICO_TEMPERATURA = "greenhealth/sensores/temperatura";
const char* TOPICO_UMIDADE_AR = "greenhealth/sensores/umidade_ar";
const char* TOPICO_DATA_HORA = "greenhealth/sensores/data_hora";
const char* TOPICO_JSON = "greenhealth/sensores/dados";

// ================= OBJETOS WIFI/MQTT =================
WiFiClient espClient;
PubSubClient mqtt(espClient);

// ================= DHT =================
#define DHTPIN 5
#define DHTTYPE DHT11

DHT dht(DHTPIN, DHTTYPE);

// ================= LED RGB =================
#define LED_R 16
#define LED_G 17
#define LED_B 18

// ================= RTC =================
#define RTC_SDA 19
#define RTC_SCL 21
#define RTC_ADDRESS 0x68

RTC_DS3231 rtc;
bool rtcDetectado = false;

// ================= CONFIGURAÇÃO DAS PLANTAS =================
#define MAX_PLANTAS 10

struct Planta {
  int numero;
  int pinoLdr;
  int pinoUmidade;
  bool ativa;
};

Planta plantas[MAX_PLANTAS];
int totalPlantas = 0;

// ================= CONTROLE DE ENVIO =================
unsigned long ultimoEnvio = 0;
const unsigned long intervaloEnvio = 1000;

unsigned long ultimoStatusSerial = 0;
const unsigned long intervaloStatusSerial = 5000;

// ================= ADICIONAR PLANTA =================
void adicionarPlanta(int numero, int pinoLdr, int pinoUmidade) {
  if (totalPlantas >= MAX_PLANTAS) {
    Serial.println("Limite máximo de plantas atingido!");
    return;
  }

  if (pinoLdr == DHTPIN || pinoUmidade == DHTPIN) {
    Serial.println("ERRO: Uma planta está tentando usar o mesmo pino do DHT!");
    Serial.print("Pino do DHT: GPIO ");
    Serial.println(DHTPIN);
    Serial.println("Altere o pino do LDR ou da umidade dessa planta.");
    Serial.println();
    return;
  }

  plantas[totalPlantas].numero = numero;
  plantas[totalPlantas].pinoLdr = pinoLdr;
  plantas[totalPlantas].pinoUmidade = pinoUmidade;
  plantas[totalPlantas].ativa = true;

  pinMode(pinoLdr, INPUT);
  pinMode(pinoUmidade, INPUT);

  Serial.print("Planta ");
  Serial.print(numero);
  Serial.println(" configurada.");

  Serial.print("LDR: GPIO ");
  Serial.println(pinoLdr);

  Serial.print("Umidade do solo: GPIO ");
  Serial.println(pinoUmidade);

  Serial.println();

  totalPlantas++;
}

// ================= FUNÇÃO WIFI =================
void conectarWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("Conectando ao WiFi");

  while (WiFi.status() != WL_CONNECTED) {
    Serial.print(".");
    delay(500);
  }

  Serial.println();
  Serial.println("WiFi conectado!");

  Serial.print("IP: ");
  Serial.println(WiFi.localIP());
}

// ================= FUNÇÃO MQTT =================
void conectarMQTT() {
  while (!mqtt.connected()) {
    Serial.print("Conectando ao MQTT... ");

    if (mqtt.connect(MQTT_CLIENT_ID)) {
      Serial.println("conectado!");
    } else {
      Serial.print("falhou. Estado: ");
      Serial.println(mqtt.state());
      ledVermelho();
      delay(2000);
    }
  }
}

// ================= IMPRIMIR STATUS NO SERIAL =================
void imprimirStatusConexao() {
  Serial.println("========== STATUS DE CONEXÃO ==========");

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("WiFi: conectado");

    Serial.print("SSID: ");
    Serial.println(WiFi.SSID());

    Serial.print("IP: ");
    Serial.println(WiFi.localIP());

    Serial.print("RSSI: ");
    Serial.print(WiFi.RSSI());
    Serial.println(" dBm");
  } else {
    Serial.println("WiFi: desconectado");
  }

  if (mqtt.connected()) {
    Serial.println("MQTT: conectado");
  } else {
    Serial.println("MQTT: desconectado");

    Serial.print("Estado MQTT: ");
    Serial.println(mqtt.state());
  }

  Serial.print("RTC: ");
  Serial.println(rtcDetectado ? "detectado" : "não detectado");

  Serial.print("Plantas ativas: ");
  Serial.println(totalPlantas);

  Serial.print("Tempo ligado: ");
  Serial.print(millis() / 1000);
  Serial.println(" segundos");

  Serial.println("========================================");
  Serial.println();
}

// ================= PUBLICAR VALOR INTEIRO =================
void publicarInt(const char* topico, int valor) {
  char mensagem[20];
  sprintf(mensagem, "%d", valor);
  mqtt.publish(topico, mensagem);
}

// ================= PUBLICAR VALOR FLOAT =================
void publicarFloat(const char* topico, float valor) {
  char mensagem[20];
  dtostrf(valor, 6, 2, mensagem);
  mqtt.publish(topico, mensagem);
}

// ================= VERIFICAR SE RTC ESTÁ PRESENTE =================
bool verificarRtcI2C() {
  Wire.beginTransmission(RTC_ADDRESS);
  byte erro = Wire.endTransmission();

  return erro == 0;
}

// ================= FORMATAR DATA E HORA DO RTC =================
String formatarDataHoraRTC(DateTime agora) {
  char dataHora[25];

  sprintf(
    dataHora,
    "%02d/%02d/%04d %02d:%02d:%02d",
    agora.day(),
    agora.month(),
    agora.year(),
    agora.hour(),
    agora.minute(),
    agora.second());

  return String(dataHora);
}

// ================= CONFIGURAR RTC =================
void configurarRTC() {
  Wire.begin(RTC_SDA, RTC_SCL);
  Serial.println("Inicializando RTC...");
  if (!verificarRtcI2C()) {
    rtcDetectado = false;
    Serial.println("ERRO: DS3231 nao encontrado.");
    return;
  }
  if (!rtc.begin()) {
    rtcDetectado = false;
    Serial.println("ERRO: Falha ao iniciar DS3231.");
    return;
  }
  rtcDetectado = true;
  if (rtc.lostPower()) rtc.adjust(DateTime(F(__DATE__), F(__TIME__)));
}

String obterDataHora() {
  if (!rtcDetectado) return "RTC_INDISPONIVEL";
  if (!verificarRtcI2C()) {
    rtcDetectado = false;
    return "RTC_DESCONECTADO";
  }
  return formatarDataHoraRTC(rtc.now());
}

// ================= PUBLICAR DADOS DAS PLANTAS =================
String montarJsonPlantas() {
  String jsonPlantas = "\"plantas\":[";

  bool primeiraPlantaNoJson = true;

  for (int i = 0; i < totalPlantas; i++) {
    if (!plantas[i].ativa) {
      continue;
    }

    int valorLdr = analogRead(plantas[i].pinoLdr);
    int valorUmidade = analogRead(plantas[i].pinoUmidade);

    int numero = plantas[i].numero;

    char topicoLdr[60];
    char topicoUmidade[60];

    sprintf(topicoLdr, "greenhealth/planta%d/ldr", numero);
    sprintf(topicoUmidade, "greenhealth/planta%d/umidade", numero);

    publicarInt(topicoLdr, valorLdr);
    publicarInt(topicoUmidade, valorUmidade);

    if (!primeiraPlantaNoJson) {
      jsonPlantas += ",";
    }

    jsonPlantas += "{";
    jsonPlantas += "\"planta\":" + String(numero) + ",";
    jsonPlantas += "\"ldr\":" + String(valorLdr) + ",";
    jsonPlantas += "\"umidade_solo\":" + String(valorUmidade);
    jsonPlantas += "}";

    primeiraPlantaNoJson = false;
  }

  jsonPlantas += "]";

  return jsonPlantas;
}


// ================= LED RGB =================
void setLed(bool r, bool g, bool b) {
  digitalWrite(LED_R, r);
  digitalWrite(LED_G, g);
  digitalWrite(LED_B, b);
}
void ledAzul() {
  setLed(0, 0, 1);
}
void ledAmarelo() {
  setLed(1, 1, 0);
}
void ledCiano() {
  setLed(0, 1, 1);
}
void ledRoxo() {
  setLed(1, 0, 1);
}
void ledVerde() {
  setLed(0, 1, 0);
}
void ledVermelho() {
  setLed(1, 0, 0);
}
void ledBranco() {
  setLed(1, 1, 1);
}
void atualizarStatusLed(bool sensorOk) {

  if (!mqtt.connected()) {
    // MQTT desconectado
    ledVermelho();
  } else if (!sensorOk) {
    // DHT com erro
    ledAmarelo();
  } else {
    // Sistema funcionando normalmente
    ledVerde();
  }
}

// ================= SETUP =================
void setup() {
  Serial.begin(115200);
  pinMode(LED_R, OUTPUT);
  pinMode(LED_G, OUTPUT);
  pinMode(LED_B, OUTPUT);

  // ================= CONFIGURE AS PLANTAS AQUI =================
  // Formato:
  // adicionarPlanta(numero, pinoLdr, pinoUmidade);

  adicionarPlanta(1, 33, 32);
  adicionarPlanta(2, 33, 35);
  adicionarPlanta(3, 33, 34);

  // ================= DHT =================
  dht.begin();

  // ================= RTC =================
  configurarRTC();

  // ================= WIFI =================
  conectarWiFi();

  // ================= MQTT =================
  mqtt.setServer(MQTT_BROKER, MQTT_PORT);
  conectarMQTT();
}

// ================= LOOP =================
void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    conectarWiFi();
  }

  if (!mqtt.connected()) {
    conectarMQTT();
  }

  mqtt.loop();

  unsigned long agoraMillis = millis();

  // ================= IMPRIME STATUS NO TERMINAL =================
  if (agoraMillis - ultimoStatusSerial >= intervaloStatusSerial) {
    ultimoStatusSerial = agoraMillis;
    imprimirStatusConexao();
  }

  // ================= ENVIO DOS SENSORES =================
  if (agoraMillis - ultimoEnvio >= intervaloEnvio) {
    ultimoEnvio = agoraMillis;

    float temperatura = dht.readTemperature();
    float umidadeAr = dht.readHumidity();

    bool sensorOk = !(isnan(temperatura) || isnan(umidadeAr));

    // Atualiza o LED conforme o estado do sistema
    atualizarStatusLed(sensorOk);

    // Primeiro usa RTC. Se falhar, usa API.
    String dataHora = obterDataHora();

    delay(60);

    // ================= PUBLICA DHT =================
    if (!isnan(temperatura)) {
      publicarFloat(TOPICO_TEMPERATURA, temperatura);
    }

    if (!isnan(umidadeAr)) {
      publicarFloat(TOPICO_UMIDADE_AR, umidadeAr);
    }

    // ================= PUBLICA DATA E HORA =================
    mqtt.publish(TOPICO_DATA_HORA, dataHora.c_str());

    // ================= MONTA JSON GERAL =================
    String json = "{";

    json += montarJsonPlantas();
    json += ",";

    if (!isnan(temperatura)) {
      json += "\"temperatura\":" + String(temperatura, 2) + ",";
    } else {
      json += "\"temperatura\":null,";
    }

    if (!isnan(umidadeAr)) {
      json += "\"umidade_ar\":" + String(umidadeAr, 2) + ",";
    } else {
      json += "\"umidade_ar\":null,";
    }

    json += "\"data_hora\":\"" + dataHora + "\"";

    json += "}";

    mqtt.publish(TOPICO_JSON, json.c_str());

    Serial.println("Dados enviados via MQTT:");
    Serial.println(json);
    Serial.println();
  }
}