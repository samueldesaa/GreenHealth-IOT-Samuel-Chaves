#include <Wire.h>
#include "RTClib.h"

RTC_DS3231 rtc;

// Pinos I2C do ESP32
#define SDA_PIN 19
#define SCL_PIN 21

void setup() {
  Serial.begin(115200);
  delay(1000);

  Wire.begin(SDA_PIN, SCL_PIN);

  if (!rtc.begin()) {
    Serial.println("RTC DS3231 não encontrado!");
    while (1);
  }

  // Ajusta o RTC com a data e hora do computador no momento da compilação
  rtc.adjust(DateTime(F(__DATE__), F(__TIME__)));

  Serial.println("RTC ajustado com sucesso!");
}

void loop() {
  DateTime agora = rtc.now();

  Serial.print("Data/Hora: ");
  Serial.print(agora.day());
  Serial.print("/");
  Serial.print(agora.month());
  Serial.print("/");
  Serial.print(agora.year());
  Serial.print(" ");
  Serial.print(agora.hour());
  Serial.print(":");
  Serial.print(agora.minute());
  Serial.print(":");
  Serial.println(agora.second());

  delay(1000);
}