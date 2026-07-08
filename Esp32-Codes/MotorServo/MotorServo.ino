#include <ESP32Servo.h>

Servo servo26;
Servo servo27;

#define SERVO_PIN_26 26
#define SERVO_PIN_27 27

// Delay entre acionar um servo e outro
// 1000 = 1 segundo
const int DELAY_ENTRE_SERVOS = 1000;

int anguloServo26 = 90;
int anguloServo27 = 90;

void setup() {
  Serial.begin(115200);

  servo26.setPeriodHertz(50);
  servo27.setPeriodHertz(50);

  servo26.attach(SERVO_PIN_26, 500, 2400);
  servo27.attach(SERVO_PIN_27, 500, 2400);

  // Posição inicial
  servo26.write(anguloServo26);
  delay(DELAY_ENTRE_SERVOS);

  servo27.write(anguloServo27);
  delay(DELAY_ENTRE_SERVOS);

  Serial.println("Controle de 2 servos iniciado.");
  Serial.println("Digite os angulos no formato:");
  Serial.println("SERVO26 SERVO27");
  Serial.println("Exemplo: 0 90");
}

void loop() {
  if (Serial.available() > 0) {
    String entrada = Serial.readStringUntil('\n');
    entrada.trim();

    int espaco = entrada.indexOf(' ');

    if (espaco == -1) {
      Serial.println("Formato invalido.");
      Serial.println("Use assim: 0 90");
      return;
    }

    String valor1 = entrada.substring(0, espaco);
    String valor2 = entrada.substring(espaco + 1);

    valor1.trim();
    valor2.trim();

    int novoAnguloServo26 = valor1.toInt();
    int novoAnguloServo27 = valor2.toInt();

    if (novoAnguloServo26 < 0 || novoAnguloServo26 > 180) {
      Serial.println("Angulo do servo 26 invalido. Use de 0 a 180.");
      return;
    }

    if (novoAnguloServo27 < 0 || novoAnguloServo27 > 180) {
      Serial.println("Angulo do servo 27 invalido. Use de 0 a 180.");
      return;
    }

    anguloServo26 = novoAnguloServo26;
    anguloServo27 = novoAnguloServo27;

    Serial.println("Movendo servo do GPIO 26...");
    servo26.write(anguloServo26);

    Serial.print("Servo GPIO 26 movido para: ");
    Serial.print(anguloServo26);
    Serial.println(" graus");

    delay(DELAY_ENTRE_SERVOS);

    Serial.println("Movendo servo do GPIO 27...");
    servo27.write(anguloServo27);

    Serial.print("Servo GPIO 27 movido para: ");
    Serial.print(anguloServo27);
    Serial.println(" graus");

    delay(DELAY_ENTRE_SERVOS);

    Serial.println("Movimento finalizado.");
    Serial.println("Digite outro comando. Exemplo: 180 45");
  }
}