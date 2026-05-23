# ESP32 Smooth Video Stream Client - README

## Gereksinimler

### Donanım

* ESP32 + PSRAM önerilir
* ILI9341 TFT ekran
* XPT2046 Touchscreen
* Buzzer (opsiyonel)

---

## Gerekli Arduino Kütüphaneleri

Kurulması gerekenler:

* TFT_eSPI
* XPT2046_Touchscreen
* Preferences
* JPEGDEC
* WiFi
---

# TFT_eSPI Ayarı

`User_Setup.h` içinde kendi ekran pinlerini ayarla.

Örnek:

```cpp
#define ILI9341_DRIVER

#define TFT_MISO 19
#define TFT_MOSI 23
#define TFT_SCLK 18
#define TFT_CS   15
#define TFT_DC    2
#define TFT_RST   4
```

---

# Python Host Gereksinimleri

## Python Kur

Python 3.10+ önerilir.

---

## Gerekli Paketler

Kurulum:

```bash
pip install opencv-python numpy mss
```

---

# Dosya Yapısı

Örnek:

```txt
project/
│
├── esp32_stream_client.ino
├── host.py
└── medya/
    ├── video1.mp4
    ├── image1.jpg
    └── image2.png
```

---

# Python Host Ayarları

Kod içinden:

```python
VIDEO_PATH = "medya"
PORT = 8080
```

---

# VIDEO_PATH Seçenekleri

## Ekran Paylaşımı

```python
VIDEO_PATH = "screen"
```

---

## Webcam

```python
VIDEO_PATH = "0"
```

---

## Tek Video

```python
VIDEO_PATH = "video.mp4"
```

---

## Tek Resim

```python
VIDEO_PATH = "image.jpg"
```

---

## Slideshow Klasörü

```python
VIDEO_PATH = "medya"
```

Desteklenen formatlar:

* jpg
* png
* bmp
* mp4
* avi
* mkv
* mov

---

# Host Başlatma

```bash
python host.py
```

Örnek çıktı:

```txt
Server: 192.168.1.15:8080 | Mod: SLIDE
```

Buradaki IP gerekli olacak.

---

# ESP32 Kurulumu

Arduino IDE:

1. ESP32 board package kur
2. Kartı seç
3. PSRAM:

   * Tools → PSRAM → Enabled
4. Partition Scheme:

   * Huge APP önerilir

---

# ESP32 İlk Açılış

Sistem:

1. Wi-Fi tarar
2. Dokunarak ağ seçilir
3. Şifre girilir
4. IP:PORT girilir
5. Mod seçilir

---

# Modlar

## SCREEN

Daha stabil.

Özellikler:

* kötü Wi-Fi’da daha iyi
* watchdog korumalı
* uzun kullanım için uygun
* biraz daha fazla gecikme

Önerilen kullanım:

* ekran paylaşımı
* masaüstü
* slideshow

---

## STREAM

Daha hızlı.

Özellikler:

* düşük latency
* daha akıcı
* agresif TCP okuma
* güçlü Wi-Fi gerekir

Önerilen kullanım:

* video
* webcam
* hızlı animasyon

---

# Dokunmatik Kullanımı

## Keyboard

Wi-Fi şifresi için kullanılır.

Tuşlar:

* SHIFT
* DEL
* OK

---

## Numpad

IP:PORT girişi:

Örnek:

```txt
192.168.1.15:8080
```

---

# Performans Ayarları

Python tarafı:

```python
TARGET_FPS = 15
VIDEO_JPEG_QUALITY = 90
```

---

## Daha Akıcı Yayın

Şunları düşür:

```python
TARGET_FPS = 10
VIDEO_JPEG_QUALITY = 70
```

---

# Olası Sorunlar

## Watchdog Reset

Sebep:

* Wi-Fi zayıf
* FPS yüksek
* JPEG quality yüksek

Çözüm:

```python
TARGET_FPS = 10
VIDEO_JPEG_QUALITY = 70
```

ve `SCREEN` modu kullan.

---

## Görüntü Donuyor

Sebep:

* packet loss
* ESP router’dan uzak
* frame boyutu büyük

Çözüm:

* router’a yaklaş
* JPEG quality düşür
* STREAM yerine SCREEN kullan

---

## Port Dolu

Hata:

```txt
Port 8080 dolu.
```

Çözüm:

```python
PORT = 9000
```

---

# Performans Notları

En iyi sonuç için:

* ESP32-WROVER kullan
* PSRAM aktif olsun
* 2.4GHz güçlü Wi-Fi kullan
* ESP router’a yakın olsun

---

# Teknik Yapı

## ESP32

* Core0:

  * Network thread
* Core1:

  * JPEG decode
  * TFT render

---

## Çift Buffer Sistemi

Kullanılan yapı:

* Buffer A
* Buffer B
* Queue system

Bu sayede:

* tearing azalır
* frame drop azalır
* decode/render paralel çalışır

---

# Proje Özeti

Bu sistem:

* PC ekranını
* videoları
* webcam görüntüsünü
* slideshow içeriklerini

ESP32 TFT ekrana gerçek zamanlı JPEG stream olarak gönderir.
