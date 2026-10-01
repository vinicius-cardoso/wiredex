"""The sample firmware's source files, as their owner would paste them in (decision 15).

Each constant is a file as a version holds it. A file a later version changes is a constant of
its own and a file it keeps is the same one, so the change between two versions is what the
later one's changelog says. The pins are the ones the sample netlists wire (requirement 10.3):
the BME280 on GPIO21 and GPIO22, at 0x76 with its SDO tied low, and the greenhouse's soil probe
on GPIO34 and pump on GPIO26.

No source here holds a backslash, which Python would read as an escape: the sketches print
with `println`, not a `\\n`. A source that needs one would be a raw string.
"""

WEATHER_STATION_INO_1_0 = """\
// Weather station: temperature, humidity and pressure from a BME280, every five minutes.
//
// The BME280 is on the ESP32's I2C bus, as the revision's netlist wires it: SDA on GPIO21,
// SCL on GPIO22, CSB tied high for I2C, and SDO tied low, which puts it at address 0x76.
// Needs the Adafruit BME280 library, from the Library Manager.

#include <Adafruit_BME280.h>
#include <Wire.h>

const int SDA_PIN = 21;
const int SCL_PIN = 22;
const uint8_t SENSOR_ADDRESS = 0x76;
const unsigned long INTERVAL_MS = 5UL * 60 * 1000;  // five minutes

Adafruit_BME280 bme;

void setup() {
  Serial.begin(115200);
  Wire.begin(SDA_PIN, SCL_PIN);
  while (!bme.begin(SENSOR_ADDRESS, &Wire)) {
    Serial.println("No BME280 at 0x76: check SDA, SCL, and that SDO is tied low");
    delay(5000);
  }
}

void loop() {
  Serial.print(bme.readTemperature(), 1);
  Serial.print(" C, ");
  Serial.print(bme.readHumidity(), 0);
  Serial.print(" %RH, ");
  Serial.print(bme.readPressure() / 100.0F, 1);
  Serial.println(" hPa");
  delay(INTERVAL_MS);
}
"""

# 1.1.0 moves the wiring and the interval here, and 1.2.0 keeps it as it is.
WEATHER_STATION_CONFIG_H = """\
// The weather station's wiring and timing, in one place.

#pragma once

#include <stdint.h>

// The BME280 on the ESP32's I2C bus, as the revision's netlist wires it: SDA on GPIO21, SCL
// on GPIO22, and SDO tied low, which puts it at address 0x76.
const int SDA_PIN = 21;
const int SCL_PIN = 22;
const uint8_t SENSOR_ADDRESS = 0x76;

// How long the board sleeps between two readings.
const uint64_t SLEEP_SECONDS = 5 * 60;
"""

WEATHER_STATION_INO_1_1 = """\
// Weather station: temperature, humidity and pressure from a BME280, every five minutes.
//
// Each reading is one wake-up: the ESP32 reads the sensor, prints what it read, and sleeps
// deeply until the next one, while the BME280, in forced mode, sleeps between measurements,
// so the station can run on a battery. The wiring and the interval are in config.h.
// Needs the Adafruit BME280 library, from the Library Manager.

#include <Adafruit_BME280.h>
#include <Wire.h>

#include "config.h"

Adafruit_BME280 bme;

void report() {
  bme.takeForcedMeasurement();
  Serial.print(bme.readTemperature(), 1);
  Serial.print(" C, ");
  Serial.print(bme.readHumidity(), 0);
  Serial.print(" %RH, ");
  Serial.print(bme.readPressure() / 100.0F, 1);
  Serial.println(" hPa");
}

void setup() {
  Serial.begin(115200);
  Wire.begin(SDA_PIN, SCL_PIN);
  if (bme.begin(SENSOR_ADDRESS, &Wire)) {
    // One measurement each time one is asked for, and the sensor asleep in between.
    bme.setSampling(Adafruit_BME280::MODE_FORCED,
                    Adafruit_BME280::SAMPLING_X1,  // temperature
                    Adafruit_BME280::SAMPLING_X1,  // pressure
                    Adafruit_BME280::SAMPLING_X1,  // humidity
                    Adafruit_BME280::FILTER_OFF);
    report();
  } else {
    Serial.println("No BME280 at 0x76: check SDA, SCL, and that SDO is tied low");
  }
  Serial.flush();
  esp_sleep_enable_timer_wakeup(SLEEP_SECONDS * 1000000ULL);
  esp_deep_sleep_start();
}

void loop() {
  // Never reached: each wake-up from deep sleep starts over in setup().
}
"""

WEATHER_STATION_INO_1_2 = """\
// Weather station: temperature, humidity and pressure from a BME280, every five minutes.
//
// Each reading is one wake-up: the ESP32 reads the sensor, prints what it read, and sleeps
// deeply until the next one, while the BME280, in forced mode, sleeps between measurements,
// so the station can run on a battery. The wiring and the interval are in config.h.
// Needs the Adafruit BME280 library, from the Library Manager.

#include <Adafruit_BME280.h>
#include <Wire.h>

#include "config.h"

// A reading is the average of this many measurements, which smooths out the sensor's noise.
const int MEASUREMENTS = 3;

Adafruit_BME280 bme;

void report() {
  float temperature = 0;
  float humidity = 0;
  float pressure = 0;
  for (int i = 0; i < MEASUREMENTS; i++) {
    bme.takeForcedMeasurement();
    temperature += bme.readTemperature();
    humidity += bme.readHumidity();
    pressure += bme.readPressure();
  }
  Serial.print(temperature / MEASUREMENTS, 1);
  Serial.print(" C, ");
  Serial.print(humidity / MEASUREMENTS, 0);
  Serial.print(" %RH, ");
  Serial.print(pressure / MEASUREMENTS / 100.0F, 1);
  Serial.println(" hPa");
}

void setup() {
  Serial.begin(115200);
  Wire.begin(SDA_PIN, SCL_PIN);
  if (bme.begin(SENSOR_ADDRESS, &Wire)) {
    // One measurement each time one is asked for, and the sensor asleep in between.
    bme.setSampling(Adafruit_BME280::MODE_FORCED,
                    Adafruit_BME280::SAMPLING_X1,  // temperature
                    Adafruit_BME280::SAMPLING_X1,  // pressure
                    Adafruit_BME280::SAMPLING_X1,  // humidity
                    Adafruit_BME280::FILTER_OFF);
    report();
  } else {
    Serial.println("No BME280 at 0x76: check SDA, SCL, and that SDO is tied low");
  }
  Serial.flush();
  esp_sleep_enable_timer_wakeup(SLEEP_SECONDS * 1000000ULL);
  esp_deep_sleep_start();
}

void loop() {
  // Never reached: each wake-up from deep sleep starts over in setup().
}
"""

GREENHOUSE_INO = """\
// Greenhouse controller: waters the tomatoes when the soil dries out.
//
// The soil probe's divider is on GPIO34, an input-only ADC pin, and GPIO26 drives the gate of
// the pump's driver, pulled down so the pump stays off while the ESP32 boots. The pump starts
// when the soil reads drier than DRY and stops once it reads wetter than WET: two thresholds,
// so it doesn't switch on and off around one.

const int SOIL_PIN = 34;
const int PUMP_PIN = 26;

// Raw readings of the probe's divider, from 0 to 4095, higher when the soil is wetter. Read
// yours in dry soil and in freshly watered soil, and set these between the two.
const int DRY = 1500;
const int WET = 2300;

const unsigned long INTERVAL_MS = 1000;

bool pumping = false;

void setup() {
  Serial.begin(115200);
  pinMode(PUMP_PIN, OUTPUT);
  digitalWrite(PUMP_PIN, LOW);
}

void loop() {
  int soil = analogRead(SOIL_PIN);
  if (!pumping && soil < DRY) {
    pumping = true;
  } else if (pumping && soil > WET) {
    pumping = false;
  }
  digitalWrite(PUMP_PIN, pumping ? HIGH : LOW);
  Serial.print("soil ");
  Serial.print(soil);
  Serial.println(pumping ? ", pump on" : ", pump off");
  delay(INTERVAL_MS);
}
"""

PICO_BLINK_MAIN_1_0 = """\
# Pico blink: the on-board LED, on for half a second and off for half a second.
#
# The smallest program that shows a Pico took its firmware: MicroPython runs main.py when the
# board starts.

import time

from machine import Pin

led = Pin("LED", Pin.OUT)

while True:
    led.toggle()
    time.sleep(0.5)
"""

PICO_BLINK_MAIN_1_1 = """\
# Pico blink: the on-board LED fades in and out, once every two seconds.
#
# PWM sets how bright the LED is. The eye notices a step far more in a dim LED than in a
# bright one, so the duty grows as the square of the step, and the fade looks even.

import time

from machine import PWM, Pin

STEPS = 256

led = PWM(Pin("LED"))
led.freq(1000)

while True:
    for step in range(STEPS):
        led.duty_u16(step * step)
        time.sleep_ms(4)
    for step in range(STEPS - 1, -1, -1):
        led.duty_u16(step * step)
        time.sleep_ms(4)
"""
