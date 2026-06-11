# 🌱 GreenHealth IoT

![Status](https://img.shields.io/badge/status-em%20desenvolvimento-yellow)
![ESP32](https://img.shields.io/badge/hardware-ESP32-blue)
![MQTT](https://img.shields.io/badge/protocolo-MQTT-green)
![IoT](https://img.shields.io/badge/projeto-IoT-brightgreen)
![Arduino](https://img.shields.io/badge/Arduino_IDE-00979D?logo=arduino&logoColor=white)
![HTML5](https://img.shields.io/badge/HTML5-E34F26?logo=html5&logoColor=white)
![CSS3](https://img.shields.io/badge/CSS3-1572B6?logo=css3&logoColor=white)
![JavaScript](https://img.shields.io/badge/JavaScript-F7DF1E?logo=javascript&logoColor=black)

---


# 🌱 GreenHealth IoT

O **GreenHealth IoT** é uma versão reduzida do projeto GreenHealth, desenvolvida com foco em **Internet das Coisas (IoT)** para monitoramento ambiental de plantas domésticas. A proposta é utilizar sensores conectados a um microcontrolador ESP32 para coletar dados do ambiente e enviá-los em tempo real por meio do protocolo MQTT.

Esta versão tem como objetivo demonstrar, de forma prática e funcional, como sensores podem ser integrados a uma interface web para acompanhar variáveis importantes no cuidado de plantas, como **umidade do solo**, **luminosidade**, **temperatura** e **umidade do ar**.

---

## 📌 Sobre o projeto

Cuidar de plantas domésticas pode ser uma tarefa difícil quando a rega e a exposição à luz são feitas apenas pela observação do usuário. Muitas vezes, a planta pode receber água em excesso, ficar em ambientes com pouca luminosidade ou sofrer com variações de temperatura e umidade sem que o usuário perceba rapidamente.

Pensando nisso, o **GreenHealth IoT** busca auxiliar no acompanhamento dessas condições por meio de sensores e comunicação em tempo real. Os dados coletados pelo ESP32 são enviados para um broker MQTT e exibidos em uma interface web com gráficos e indicadores visuais.

Esta versão reduzida não possui todos os recursos previstos no projeto completo, como inteligência artificial, perfis botânicos avançados ou irrigação automatizada completa, mas serve como uma base funcional para validar a comunicação entre hardware, sensores, MQTT e dashboard web.

---

## 🎯 Objetivo

Desenvolver um protótipo IoT capaz de monitorar dados ambientais relacionados ao cuidado de plantas domésticas e disponibilizar essas informações em uma interface web em tempo real.

---

## 🧠 Ideia principal

O sistema funciona com a seguinte lógica:

1. O ESP32 lê os dados dos sensores conectados.
2. Os dados são organizados e enviados por MQTT.
3. Um broker MQTT recebe e distribui as mensagens.
4. A interface web se conecta ao broker.
5. Os valores são exibidos em gráficos e indicadores para o usuário.

---

## 🛠️ Tecnologias utilizadas

### Hardware

- ESP32
- Sensores de umidade do solo
- Sensores LDR para luminosidade
- Sensor DHT para temperatura e umidade do ar
- Jumpers
- Protoboard
- Fonte de alimentação ou cabo USB

### Software

- Arduino IDE
- HTML
- CSS
- JavaScript
- MQTT
- Broker EMQX público
- Biblioteca PubSubClient
- Biblioteca WiFi
- Chart.js
- Eclipse Paho MQTT

---

## 📡 Comunicação MQTT

O projeto utiliza MQTT para permitir a comunicação entre o ESP32 e a interface web.

### Broker utilizado

```txt
broker.emqx.io
