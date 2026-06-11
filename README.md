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

## 🌿 Sobre o projeto

O **GreenHealth IoT** é uma versão reduzida do projeto **GreenHealth**, desenvolvida com foco em **Internet das Coisas** para o monitoramento de plantas domésticas.

A ideia principal é utilizar um **ESP32** conectado a sensores para coletar informações do ambiente e das plantas, como **umidade do solo**, **luminosidade**, **temperatura** e **umidade do ar**. Esses dados são enviados em tempo real por meio do protocolo **MQTT** e exibidos em uma interface web com gráficos e indicadores visuais.

Esta versão tem como objetivo validar a comunicação entre **hardware, sensores, MQTT e dashboard web**, servindo como uma base prática para futuras evoluções do sistema completo.

---

## 🎯 Objetivo

Desenvolver um protótipo IoT capaz de monitorar variáveis ambientais relacionadas ao cuidado de plantas domésticas e disponibilizar esses dados em uma interface web em tempo real.

---

## 🧠 Como funciona?

```txt
🌱 Sensores
   ↓
📟 ESP32
   ↓ MQTT
☁️ Broker EMQX
   ↓ WebSocket
💻 Dashboard Web
   ↓
👤 Usuário
