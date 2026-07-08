#include <WiFi.h>
#include <PubSubClient.h>
#include <ESP32Servo.h>
#include <Wire.h>
#include "DHT.h"
#include "RTClib.h"

// ================= WIFI =================
const char* WIFI_SSID = "S20FE";
const char* WIFI_PASSWORD = "samuelsa";

// ================= MQTT =================
const char* MQTT_BROKER = "broker.emqx.io";
const int MQTT_PORT = 1883;

// IMPORTANTE:
// Agora o Client ID fica mais único para evitar conflito no broker público.
String MQTT_CLIENT_ID = "esp32_greenhealth_samuel_" + String((uint32_t)ESP.getEfuseMac(), HEX);

// Aumenta o tamanho máximo dos pacotes MQTT.
// O padrão do PubSubClient pode ser pequeno para JSON com várias plantas.
const int MQTT_BUFFER_SIZE = 1024;

// ================= TÓPICOS GERAIS =================
const char* TOPICO_TEMPERATURA = "greenhealth/sensores/temperatura";
const char* TOPICO_UMIDADE_AR = "greenhealth/sensores/umidade_ar";
const char* TOPICO_DATA_HORA = "greenhealth/sensores/data_hora";
const char* TOPICO_JSON = "greenhealth/sensores/dados";

// Comando dos servos:
// greenhealth/planta1/servo
// greenhealth/planta2/servo
// greenhealth/planta3/servo
const char* TOPICO_COMANDO_SERVOS = "greenhealth/+/servo";

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

// ================= SERVOS =================
// Ajuste de acordo com seu mecanismo físico.
const int ANGULO_SERVO_FECHADO = 0;
const int ANGULO_SERVO_ABERTO = 90;

// Como a página web usa deslizador de 0 a 90,
// o código também limita o controle manual até 90.
const int ANGULO_MINIMO_USUARIO = 0;
const int ANGULO_MAXIMO_USUARIO = 90;

// Tempo que o servo fica aberto ao receber "ativar" ou "regar".
const unsigned long TEMPO_SERVO_ATIVO = 1200;

// Delay para evitar queda de alimentação ao movimentar servos.
const int DELAY_ENTRE_SERVOS = 1000;

// ================= CONFIGURAÇÃO DAS PLANTAS =================
#define MAX_PLANTAS 10

struct Planta {
  int numero;
  int pinoLdr;
  int pinoUmidade;
  int pinoServo;
  int anguloServoAtual;
  bool ativa;
  Servo servo;
};

Planta plantas[MAX_PLANTAS];
int totalPlantas = 0;

// ================= CONTROLE DE ENVIO =================
// DHT11 fica mais estável com leitura a cada 2 segundos.
unsigned long ultimoEnvio = 0;
const unsigned long intervaloEnvio = 2000;

unsigned long ultimoStatusSerial = 0;
const unsigned long intervaloStatusSerial = 5000;

// ================= FUNÇÕES AUXILIARES =================
bool pinoApenasEntrada(int pino) {
  return pino >= 34 && pino <= 39;
}

bool textoEhNumeroInteiro(String texto) {
  texto.trim();

  if (texto.length() == 0) {
    return false;
  }

  for (int i = 0; i < texto.length(); i++) {
    if (!isDigit(texto.charAt(i))) {
      return false;
    }
  }

  return true;
}

Planta* buscarPlantaPorNumero(int numero) {
  for (int i = 0; i < totalPlantas; i++) {
    if (plantas[i].numero == numero && plantas[i].ativa) {
      return &plantas[i];
    }
  }

  return nullptr;
}

int extrairNumeroPlantaDoTopico(String topico) {
  int posPlanta = topico.indexOf("planta");

  if (posPlanta == -1) {
    return -1;
  }

  int inicioNumero = posPlanta + 6;
  int fimNumero = topico.indexOf("/", inicioNumero);

  if (fimNumero == -1) {
    return -1;
  }

  String numeroTexto = topico.substring(inicioNumero, fimNumero);
  numeroTexto.trim();

  if (!textoEhNumeroInteiro(numeroTexto)) {
    return -1;
  }

  return numeroTexto.toInt();
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

void ledVerde() {
  setLed(0, 1, 0);
}

void ledVermelho() {
  setLed(1, 0, 0);
}

void atualizarStatusLed(bool sensorOk) {
  if (!mqtt.connected()) {
    ledVermelho();
  } else if (!sensorOk) {
    ledAmarelo();
  } else {
    ledVerde();
  }
}

// ================= PUBLICAÇÃO MQTT COM DEBUG =================
bool publicarTexto(const char* topico, const char* mensagem) {
  if (!mqtt.connected()) {
    Serial.print("MQTT desconectado. Nao publicou em: ");
    Serial.println(topico);
    return false;
  }

  bool sucesso = mqtt.publish(topico, mensagem);

  if (!sucesso) {
    Serial.println();
    Serial.println("ERRO AO PUBLICAR MQTT!");
    Serial.print("Topico: ");
    Serial.println(topico);
    Serial.print("Tamanho da mensagem: ");
    Serial.println(strlen(mensagem));
    Serial.print("Mensagem: ");
    Serial.println(mensagem);
    Serial.println("Possivel causa: buffer MQTT pequeno ou conexao instavel.");
    Serial.println();
  }

  return sucesso;
}

void publicarInt(const char* topico, int valor) {
  char mensagem[20];
  sprintf(mensagem, "%d", valor);
  publicarTexto(topico, mensagem);
}

void publicarFloat(const char* topico, float valor) {
  char mensagem[20];
  dtostrf(valor, 6, 2, mensagem);
  publicarTexto(topico, mensagem);
}

// ================= CONTROLE DOS SERVOS =================
void publicarStatusServo(int numeroPlanta, const char* status) {
  char topicoStatus[80];
  sprintf(topicoStatus, "greenhealth/planta%d/servo/status", numeroPlanta);
  publicarTexto(topicoStatus, status);
}

void publicarAnguloServo(int numeroPlanta, int angulo) {
  char topicoAngulo[80];
  char mensagem[20];

  sprintf(topicoAngulo, "greenhealth/planta%d/servo/angulo", numeroPlanta);
  sprintf(mensagem, "%d", angulo);

  publicarTexto(topicoAngulo, mensagem);
}

void moverServoPlanta(int numeroPlanta, int angulo) {
  Planta* planta = buscarPlantaPorNumero(numeroPlanta);

  if (planta == nullptr) {
    Serial.print("ERRO: Planta ");
    Serial.print(numeroPlanta);
    Serial.println(" nao encontrada para mover servo.");
    return;
  }

  if (angulo < ANGULO_MINIMO_USUARIO || angulo > ANGULO_MAXIMO_USUARIO) {
    Serial.print("ERRO: Angulo invalido. Use de ");
    Serial.print(ANGULO_MINIMO_USUARIO);
    Serial.print(" a ");
    Serial.print(ANGULO_MAXIMO_USUARIO);
    Serial.println(" graus.");
    return;
  }

  Serial.println();
  Serial.print("Movendo servo da Planta ");
  Serial.print(numeroPlanta);
  Serial.print(" | GPIO ");
  Serial.print(planta->pinoServo);
  Serial.print(" | Angulo ");
  Serial.println(angulo);

  ledAzul();

  planta->servo.write(angulo);
  planta->anguloServoAtual = angulo;

  publicarAnguloServo(numeroPlanta, angulo);

  char status[40];
  sprintf(status, "angulo_%d", angulo);
  publicarStatusServo(numeroPlanta, status);

  delay(DELAY_ENTRE_SERVOS);
}

void abrirServoPlanta(int numeroPlanta) {
  moverServoPlanta(numeroPlanta, ANGULO_SERVO_ABERTO);
  publicarStatusServo(numeroPlanta, "aberto");
}

void fecharServoPlanta(int numeroPlanta) {
  moverServoPlanta(numeroPlanta, ANGULO_SERVO_FECHADO);
  publicarStatusServo(numeroPlanta, "fechado");
}

void acionarServoPlanta(int numeroPlanta) {
  Planta* planta = buscarPlantaPorNumero(numeroPlanta);

  if (planta == nullptr) {
    Serial.print("ERRO: Planta ");
    Serial.print(numeroPlanta);
    Serial.println(" nao encontrada para acionar servo.");
    return;
  }

  Serial.println();
  Serial.print("Ativando irrigacao da Planta ");
  Serial.print(numeroPlanta);
  Serial.print(" pelo servo GPIO ");
  Serial.println(planta->pinoServo);

  ledAzul();

  publicarStatusServo(numeroPlanta, "abrindo");

  planta->servo.write(ANGULO_SERVO_ABERTO);
  planta->anguloServoAtual = ANGULO_SERVO_ABERTO;
  publicarAnguloServo(numeroPlanta, ANGULO_SERVO_ABERTO);

  delay(TEMPO_SERVO_ATIVO);

  planta->servo.write(ANGULO_SERVO_FECHADO);
  planta->anguloServoAtual = ANGULO_SERVO_FECHADO;
  publicarAnguloServo(numeroPlanta, ANGULO_SERVO_FECHADO);

  publicarStatusServo(numeroPlanta, "acionado_e_fechado");

  Serial.print("Irrigacao da Planta ");
  Serial.print(numeroPlanta);
  Serial.println(" finalizada.");

  delay(DELAY_ENTRE_SERVOS);
}

// ================= CALLBACK MQTT =================
void callbackMQTT(char* topic, byte* payload, unsigned int length) {
  String topico = String(topic);
  String mensagem = "";

  for (unsigned int i = 0; i < length; i++) {
    mensagem += (char)payload[i];
  }

  mensagem.trim();

  String comando = mensagem;
  comando.toLowerCase();

  Serial.println();
  Serial.println("========== COMANDO MQTT RECEBIDO ==========");
  Serial.print("Topico: ");
  Serial.println(topico);
  Serial.print("Mensagem: ");
  Serial.println(mensagem);

  if (!topico.endsWith("/servo")) {
    Serial.println("Topico ignorado. Nao e comando de servo.");
    Serial.println("===========================================");
    return;
  }

  int numeroPlanta = extrairNumeroPlantaDoTopico(topico);

  if (numeroPlanta <= 0) {
    Serial.println("ERRO: Nao foi possivel identificar o numero da planta.");
    Serial.println("Use: greenhealth/planta1/servo");
    Serial.println("===========================================");
    return;
  }

  if (comando == "ativar" || comando == "regar" || comando == "1") {
    acionarServoPlanta(numeroPlanta);
  }
  else if (comando == "abrir" || comando == "open") {
    abrirServoPlanta(numeroPlanta);
  }
  else if (comando == "fechar" || comando == "off") {
    fecharServoPlanta(numeroPlanta);
  }
  else if (textoEhNumeroInteiro(comando)) {
    int angulo = comando.toInt();
    moverServoPlanta(numeroPlanta, angulo);
  }
  else {
    Serial.println("Comando invalido.");
    Serial.println("Use: ativar, regar, abrir, fechar ou angulo de 0 a 90.");
  }

  Serial.println("===========================================");
  Serial.println();
}

// ================= ADICIONAR PLANTA =================
void adicionarPlanta(int numero, int pinoLdr, int pinoUmidade, int pinoServo) {
  if (totalPlantas >= MAX_PLANTAS) {
    Serial.println("Limite maximo de plantas atingido!");
    return;
  }

  if (pinoLdr == DHTPIN || pinoUmidade == DHTPIN || pinoServo == DHTPIN) {
    Serial.println("ERRO: Uma planta esta tentando usar o mesmo pino do DHT!");
    Serial.print("Pino do DHT: GPIO ");
    Serial.println(DHTPIN);
    Serial.println();
    return;
  }

  if (pinoServo == RTC_SDA || pinoServo == RTC_SCL) {
    Serial.println("ERRO: Servo tentando usar pino reservado para RTC!");
    Serial.println();
    return;
  }

  if (pinoServo == LED_R || pinoServo == LED_G || pinoServo == LED_B) {
    Serial.println("ERRO: Servo tentando usar pino reservado para LED RGB!");
    Serial.println();
    return;
  }

  if (pinoServo == pinoLdr || pinoServo == pinoUmidade) {
    Serial.println("ERRO: Servo usando o mesmo pino de sensor da planta!");
    Serial.println();
    return;
  }

  if (pinoApenasEntrada(pinoServo)) {
    Serial.print("ERRO: GPIO ");
    Serial.print(pinoServo);
    Serial.println(" e apenas entrada no ESP32 e nao pode controlar servo.");
    Serial.println();
    return;
  }

  plantas[totalPlantas].numero = numero;
  plantas[totalPlantas].pinoLdr = pinoLdr;
  plantas[totalPlantas].pinoUmidade = pinoUmidade;
  plantas[totalPlantas].pinoServo = pinoServo;
  plantas[totalPlantas].anguloServoAtual = ANGULO_SERVO_FECHADO;
  plantas[totalPlantas].ativa = true;

  pinMode(pinoLdr, INPUT);
  pinMode(pinoUmidade, INPUT);

  plantas[totalPlantas].servo.setPeriodHertz(50);
  plantas[totalPlantas].servo.attach(pinoServo, 500, 2400);
  plantas[totalPlantas].servo.write(ANGULO_SERVO_FECHADO);

  Serial.println();
  Serial.print("Planta ");
  Serial.print(numero);
  Serial.println(" configurada.");

  Serial.print("LDR: GPIO ");
  Serial.println(pinoLdr);

  Serial.print("Umidade do solo: GPIO ");
  Serial.println(pinoUmidade);

  Serial.print("Servo: GPIO ");
  Serial.println(pinoServo);

  Serial.print("Topico MQTT do servo: greenhealth/planta");
  Serial.print(numero);
  Serial.println("/servo");

  Serial.println();

  totalPlantas++;

  delay(DELAY_ENTRE_SERVOS);
}

// ================= WIFI =================
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

// ================= MQTT =================
void conectarMQTT() {
  while (!mqtt.connected()) {
    Serial.print("Conectando ao MQTT com Client ID: ");
    Serial.println(MQTT_CLIENT_ID);

    if (mqtt.connect(MQTT_CLIENT_ID.c_str())) {
      Serial.println("MQTT conectado!");

      bool inscritoServo = mqtt.subscribe(TOPICO_COMANDO_SERVOS);

      Serial.print("Inscricao no topico ");
      Serial.print(TOPICO_COMANDO_SERVOS);
      Serial.print(": ");
      Serial.println(inscritoServo ? "OK" : "FALHOU");

      Serial.println("Comandos aceitos:");
      Serial.println("greenhealth/planta1/servo -> ativar");
      Serial.println("greenhealth/planta1/servo -> 0 ate 90");
      Serial.println("greenhealth/planta1/servo -> abrir");
      Serial.println("greenhealth/planta1/servo -> fechar");
      Serial.println();
    } else {
      Serial.print("Falha MQTT. Estado: ");
      Serial.println(mqtt.state());
      ledVermelho();
      delay(2000);
    }
  }
}

// ================= STATUS SERIAL =================
void imprimirStatusConexao() {
  Serial.println("========== STATUS DE CONEXAO ==========");

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

  Serial.print("Buffer MQTT: ");
  Serial.print(MQTT_BUFFER_SIZE);
  Serial.println(" bytes");

  Serial.print("RTC: ");
  Serial.println(rtcDetectado ? "detectado" : "nao detectado");

  Serial.print("Plantas ativas: ");
  Serial.println(totalPlantas);

  for (int i = 0; i < totalPlantas; i++) {
    Serial.print("Planta ");
    Serial.print(plantas[i].numero);
    Serial.print(" | LDR GPIO ");
    Serial.print(plantas[i].pinoLdr);
    Serial.print(" | Umidade GPIO ");
    Serial.print(plantas[i].pinoUmidade);
    Serial.print(" | Servo GPIO ");
    Serial.print(plantas[i].pinoServo);
    Serial.print(" | Angulo ");
    Serial.println(plantas[i].anguloServoAtual);
  }

  Serial.print("Tempo ligado: ");
  Serial.print(millis() / 1000);
  Serial.println(" segundos");

  Serial.println("=======================================");
  Serial.println();
}

// ================= RTC =================
bool verificarRtcI2C() {
  Wire.beginTransmission(RTC_ADDRESS);
  byte erro = Wire.endTransmission();

  return erro == 0;
}

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
    agora.second()
  );

  return String(dataHora);
}

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

  if (rtc.lostPower()) {
    rtc.adjust(DateTime(F(__DATE__), F(__TIME__)));
  }

  Serial.println("RTC iniciado com sucesso.");
}

String obterDataHora() {
  if (!rtcDetectado) {
    return "RTC_INDISPONIVEL";
  }

  if (!verificarRtcI2C()) {
    rtcDetectado = false;
    return "RTC_DESCONECTADO";
  }

  return formatarDataHoraRTC(rtc.now());
}

// ================= JSON DAS PLANTAS =================
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

    char topicoLdr[80];
    char topicoUmidade[80];

    sprintf(topicoLdr, "greenhealth/planta%d/ldr", numero);
    sprintf(topicoUmidade, "greenhealth/planta%d/umidade", numero);

    publicarInt(topicoLdr, valorLdr);
    publicarInt(topicoUmidade, valorUmidade);
    publicarAnguloServo(numero, plantas[i].anguloServoAtual);

    if (!primeiraPlantaNoJson) {
      jsonPlantas += ",";
    }

    jsonPlantas += "{";
    jsonPlantas += "\"planta\":" + String(numero) + ",";
    jsonPlantas += "\"ldr\":" + String(valorLdr) + ",";
    jsonPlantas += "\"umidade_solo\":" + String(valorUmidade) + ",";
    jsonPlantas += "\"pino_servo\":" + String(plantas[i].pinoServo) + ",";
    jsonPlantas += "\"angulo_servo\":" + String(plantas[i].anguloServoAtual);
    jsonPlantas += "}";

    primeiraPlantaNoJson = false;
  }

  jsonPlantas += "]";

  return jsonPlantas;
}

// ================= SETUP =================
void setup() {
  Serial.begin(115200);

  delay(1000);

  pinMode(LED_R, OUTPUT);
  pinMode(LED_G, OUTPUT);
  pinMode(LED_B, OUTPUT);

  ledVermelho();

  // ================= CONFIGURE AS PLANTAS AQUI =================
  // Formato:
  // adicionarPlanta(numero, pinoLdr, pinoUmidade, pinoServo);

  adicionarPlanta(1, 33, 35, 26);
  adicionarPlanta(2, 36, 34, 27);
  // adicionarPlanta(3, 36, 32, 14);

  // ================= DHT =================
  dht.begin();

  // ================= RTC =================
  configurarRTC();

  // ================= WIFI =================
  conectarWiFi();

  // ================= MQTT =================
  mqtt.setServer(MQTT_BROKER, MQTT_PORT);
  mqtt.setCallback(callbackMQTT);

  // CORREÇÃO IMPORTANTE:
  // Sem isso, o JSON geral pode não ser publicado corretamente.
  mqtt.setBufferSize(MQTT_BUFFER_SIZE);

  conectarMQTT();

  ledVerde();
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

  if (agoraMillis - ultimoStatusSerial >= intervaloStatusSerial) {
    ultimoStatusSerial = agoraMillis;
    imprimirStatusConexao();
  }

  if (agoraMillis - ultimoEnvio >= intervaloEnvio) {
    ultimoEnvio = agoraMillis;

    float temperatura = dht.readTemperature();
    float umidadeAr = dht.readHumidity();

    bool sensorOk = !(isnan(temperatura) || isnan(umidadeAr));

    atualizarStatusLed(sensorOk);

    String dataHora = obterDataHora();

    if (!isnan(temperatura)) {
      publicarFloat(TOPICO_TEMPERATURA, temperatura);
    }

    if (!isnan(umidadeAr)) {
      publicarFloat(TOPICO_UMIDADE_AR, umidadeAr);
    }

    publicarTexto(TOPICO_DATA_HORA, dataHora.c_str());

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

    Serial.println();
    Serial.println("JSON GERADO:");
    Serial.println(json);
    Serial.print("Tamanho do JSON: ");
    Serial.print(json.length());
    Serial.println(" bytes");

    bool jsonPublicado = publicarTexto(TOPICO_JSON, json.c_str());

    Serial.print("Publicacao do JSON geral: ");
    Serial.println(jsonPublicado ? "OK" : "FALHOU");

    Serial.println();
  }
}