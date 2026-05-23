/*  
    ESP32 Smooth Video Stream Client (Request-Response Mode)
    
    Gereklilikler:
    - TFT_eSPI
    - XPT2046_Touchscreen
    - TJpg_Decoder
*/
// change buzzer freq gap

#include <SPI.h>
#include <TFT_eSPI.h>
#include <WiFi.h>
#include <XPT2046_Touchscreen.h>
#include <Preferences.h>
#include <TJpg_Decoder.h>

TFT_eSPI tft = TFT_eSPI();
Preferences preferences;

// --- PIN TANIMLARI ---
#define buzzerPin 26

#define XPT2046_IRQ 36
#define XPT2046_MOSI 32
#define XPT2046_MISO 39
#define XPT2046_CLK 25
#define XPT2046_CS 33

SPIClass touchscreenSPI = SPIClass(VSPI);
XPT2046_Touchscreen touchscreen(XPT2046_CS, XPT2046_IRQ);

#define SCREEN_WIDTH 320
#define SCREEN_HEIGHT 240
#define FONT_SIZE 2

// Dokunmatik Kalibrasyon
#define TS_MINX 200
#define TS_MAXX 3700
#define TS_MINY 240
#define TS_MAXY 3800

int pwmFreq = 2000;  // Ses frekansı
int pwmRes = 8;      // Çözünürlük (8 bit)

// --- GLOBAL DEĞİŞKENLER & BUFFER ---
unsigned long timeDelay = 0;
bool scan_wifi = true;
bool isStarted = false;
String targetIP = "";
WiFiClient streamClient;

// STATİK BUFFER: Sürekli hafıza oluştur/sil yapmamak için.
#define MAX_JPG_SIZE 100000
uint8_t* jpgBuffer = NULL;  // Sadece bir işaretçi (pointer) oluşturuyoruz, yer kaplamaz.
// --- KLAVYE & NUMPAD DÜZENLERİ ---
const char mobile_keyboard[4][11] = {
  { '1', '2', '3', '4', '5', '6', '7', '8', '9', '0', 0 },
  { 'Q', 'W', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P', 0 },
  { 'A', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L', 0, 0 },
  { '^', 'Z', 'X', 'C', 'V', 'B', 'N', 'M', '.', 0, 0 }
};

const char numpad_keys[4][3] = {
  { '1', '2', '3' },
  { '4', '5', '6' },
  { '7', '8', '9' },
  { '.', '0', ':' }
};

// --- YARDIMCI FONKSİYONLAR ---

String ssidToKey(String ssid) {
  unsigned long hash = 5381;
  for (int i = 0; i < ssid.length(); i++) {
    hash = ((hash << 5) + hash) + ssid.charAt(i);
  }
  return String(hash, HEX);
}

void typeWriterPrint(String text, int centerX, int y, int fontIndex) {
  // Bu fonksiyon her çağrıldığında 1 ile 255 arasında RASTGELE bir güç belirle
  int randomDuty = random(1, 256);

  // --- Konum Hesaplama (DrawCentre Mantığı) ---
  tft.setTextFont(fontIndex);
  int textWidth = tft.textWidth(text);     // Metnin piksel genişliği
  int startX = centerX - (textWidth / 2);  // Başlangıç noktası
  tft.setCursor(startX, y);                // İmleci konumlandır

  // --- Yazdırma Döngüsü ---
  for (int i = 0; i < text.length(); i++) {
    tft.print(text[i]);  // Harfi bas

    // Rastgele belirlenen güçle sesi aç
    // ESP32 v3.0'da ledcWrite artık KANAL değil PIN numarası ister.
    ledcWrite(buzzerPin, randomDuty);
    delay(10);                // Ses süresi
    ledcWrite(buzzerPin, 0);  // Sesi kapat

    delay(35);  // Harf arası bekleme
  }
}
void printWifiInfo(String ssid, String rssi, String encryption) {
  tft.fillScreen(TFT_WHITE);
  tft.setTextColor(TFT_BLACK, TFT_WHITE);
  int centerX = SCREEN_WIDTH / 2;
  typeWriterPrint("Agi Secmek Icin Dokun", centerX, 20, 2);
  tft.fillRect(20, 60, 280, 120, TFT_LIGHTGREY);
  tft.drawRect(20, 60, 280, 120, TFT_BLACK);
  tft.setTextColor(TFT_BLUE, TFT_LIGHTGREY);
  typeWriterPrint(ssid, centerX, 80, 2);
  tft.setTextColor(TFT_BLACK, TFT_LIGHTGREY);
  typeWriterPrint("Sinyal:" + rssi + " dBm", centerX, 110, 2);
  typeWriterPrint(encryption, centerX, 140, 2);
}

// TJpg_Decoder Callback (Ekrana Çizim)
bool tft_output(int16_t x, int16_t y, uint16_t w, uint16_t h, uint16_t* bitmap) {
  if (y >= SCREEN_HEIGHT) return 0;
  tft.pushImage(x, y, w, h, bitmap);
  return 1;
}

// --- ARAYÜZ FONKSİYONLARI ---

void drawKeyboard(bool isShift) {
  int keyW = 32;
  int keyH = 40;
  int startY = 80;
  tft.setTextColor(TFT_WHITE, TFT_DARKGREY);
  tft.setTextSize(1);
  for (int r = 0; r < 4; r++) {
    for (int c = 0; c < 10; c++) {
      char k = mobile_keyboard[r][c];
      if (k != 0) {
        int xPos = c * keyW + 1;
        int yPos = startY + r * keyH + 1;
        tft.fillRect(xPos, yPos, keyW - 2, keyH - 2, TFT_DARKGREY);
        tft.drawRect(xPos, yPos, keyW - 2, keyH - 2, TFT_BLACK);
        char displayChar = k;
        if (!isShift && k >= 'A' && k <= 'Z') displayChar = k + 32;
        if (k == '^') {
          if (isShift) {
            tft.fillRect(xPos, yPos, keyW - 2, keyH - 2, TFT_ORANGE);
            tft.setTextColor(TFT_BLACK, TFT_ORANGE);
          } else {
            tft.setTextColor(TFT_YELLOW, TFT_DARKGREY);
          }
          tft.drawString("SHIFT", xPos + 2, yPos + 12, 1);
          tft.setTextColor(TFT_WHITE, TFT_DARKGREY);
        } else {
          tft.drawChar(displayChar, xPos + 10, yPos + 10, 2);
        }
      }
    }
  }
  int delX = 9 * keyW + 1;
  int delY = startY + 2 * keyH + 1;
  tft.fillRect(delX, delY, keyW - 2, keyH - 2, TFT_RED);
  tft.setTextColor(TFT_WHITE, TFT_RED);
  tft.drawString("DEL", delX + 5, delY + 12, 1);
  int okX = 9 * keyW + 1;
  int okY = startY + 3 * keyH + 1;
  tft.fillRect(okX, okY, keyW - 2, keyH - 2, TFT_GREEN);
  tft.setTextColor(TFT_BLACK, TFT_GREEN);
  tft.drawString("OK", okX + 8, okY + 10, 2);
}

String getPasswordFromKeyboard(String ssidName, String savedPassword) {
  String pass = savedPassword;
  bool isShift = false;
  bool finish = false;
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  typeWriterPrint("Sifre:" + ssidName, 5, 5, 1);
  tft.drawRect(0, 40, 320, 30, TFT_WHITE);
  drawKeyboard(isShift);
  int keyW = 32;
  int keyH = 40;
  int startY = 80;
  tft.setTextColor(TFT_YELLOW, TFT_BLACK);
  typeWriterPrint(pass, 5, 47, 2);

  while (!finish) {
    tft.fillRect(2, 42, 316, 26, TFT_BLACK);
    tft.setTextColor(TFT_YELLOW, TFT_BLACK);
    tft.drawString(pass, 5, 47, 2);
    while (!touchscreen.tirqTouched()) { delay(10); }
    if (touchscreen.touched()) {
      TS_Point p = touchscreen.getPoint();
      int touch_x = map(p.x, TS_MINX, TS_MAXX, 0, SCREEN_WIDTH);
      int touch_y = map(p.y, TS_MINY, TS_MAXY, 0, SCREEN_HEIGHT);
      delay(150);
      while (touchscreen.touched()) {};
      if (touch_y > startY) {
        int r = (touch_y - startY) / keyH;
        int c = touch_x / keyW;
        if (r >= 0 && r < 4 && c >= 0 && c < 10) {
          ledcWrite(buzzerPin, 128);
          delay(10);                // Ses süresi
          ledcWrite(buzzerPin, 0);  // Sesi kapat
          if (r == 2 && c == 9) {
            if (pass.length() > 0) pass.remove(pass.length() - 1);
          } else if (r == 3 && c == 9) {
            finish = true;
            ledcWrite(buzzerPin, 255);
            delay(20);                  // Ses süresi
            ledcWrite(buzzerPin, 230);  // Sesi kapat
            delay(20);                  // Ses süresi
            ledcWrite(buzzerPin, 200);
            delay(20);                  // Ses süresi
            ledcWrite(buzzerPin, 190);  // Sesi kapat
            delay(20);                  // Ses süresi
            ledcWrite(buzzerPin, 150);  // Sesi kapat
            delay(20);                  // Ses süresi
            ledcWrite(buzzerPin, 130);
            delay(20);                // Ses süresi
            ledcWrite(buzzerPin, 0);  // Sesi kapat
          } else if (r == 3 && c == 0) {
            isShift = !isShift;
            drawKeyboard(isShift);
          } else {
            char k = mobile_keyboard[r][c];
            if (k != 0 && k != '^') {
              if (!isShift && k >= 'A' && k <= 'Z') pass += (char)(k + 32);
              else pass += k;
            }
          }
        }
      }
    }
  }
  return pass;
}

void drawNumpad() {
  int btnW = 60;
  int btnH = 38;
  int startX = 30;
  int startY = 65;
  int gap = 8;
  tft.setTextSize(2);
  for (int r = 0; r < 4; r++) {
    for (int c = 0; c < 3; c++) {
      char k = numpad_keys[r][c];
      int xPos = startX + (c * btnW);
      int yPos = startY + (r * btnH);
      tft.fillRect(xPos + 2, yPos + 2, btnW - 4, btnH - 4, TFT_DARKGREY);
      tft.drawRect(xPos + 2, yPos + 2, btnW - 4, btnH - 4, TFT_WHITE);
      tft.setTextColor(TFT_WHITE, TFT_DARKGREY);
      tft.drawChar(k, xPos + (btnW / 2) - 5, yPos + (btnH / 2) - 7, 1);
    }
  }
  int ctrlX = startX + (3 * btnW) + gap;
  int ctrlW = 65;
  int totalH = 4 * btnH;
  tft.fillRect(ctrlX, startY + 2, ctrlW, (totalH / 2) - 4, TFT_RED);
  tft.drawRect(ctrlX, startY + 2, ctrlW, (totalH / 2) - 4, TFT_WHITE);
  tft.setTextColor(TFT_WHITE, TFT_RED);
  tft.drawString("SIL", ctrlX + 15, startY + (totalH / 4) - 8, 1);
  tft.fillRect(ctrlX, startY + (totalH / 2) + 2, ctrlW, (totalH / 2) - 4, TFT_GREEN);
  tft.drawRect(ctrlX, startY + (totalH / 2) + 2, ctrlW, (totalH / 2) - 4, TFT_WHITE);
  tft.setTextColor(TFT_BLACK, TFT_GREEN);
  tft.drawString("OK", ctrlX + 20, startY + (totalH * 0.75) - 8, 1);
}

String getIPPortFromNumpad(String savedIP) {
  String currentInput = savedIP;
  bool finished = false;
  int btnW = 60;
  int btnH = 38;
  int startX = 30;
  int startY = 65;
  int gap = 8;
  int ctrlX = startX + (3 * btnW) + gap;
  int ctrlW = 65;
  int totalH = 4 * btnH;
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  typeWriterPrint("IP ve Port Girin", SCREEN_WIDTH / 2, 2, 2);
  tft.drawRect(30, 25, 260, 30, TFT_WHITE);
  drawNumpad();
  bool updateScreen = true;
  while (!finished) {
    if (updateScreen) {
      tft.fillRect(31, 26, 258, 28, TFT_BLACK);
      String textToDisplay = currentInput;
      int maxPixelWidth = 250;
      while (tft.textWidth(textToDisplay) > maxPixelWidth) { textToDisplay = textToDisplay.substring(1); }
      tft.setTextColor(TFT_YELLOW, TFT_BLACK);
      tft.drawString(textToDisplay, 35, 32, 1);
      updateScreen = false;
    }
    if (touchscreen.tirqTouched() && touchscreen.touched()) {
      TS_Point p = touchscreen.getPoint();
      int t_x = map(p.x, TS_MINX, TS_MAXX, 0, SCREEN_WIDTH);
      int t_y = map(p.y, TS_MINY, TS_MAXY, 0, SCREEN_HEIGHT);
      delay(200);
      while (touchscreen.touched())
        ;
      if (t_x >= startX && t_x < ctrlX && t_y >= startY && t_y < startY + totalH) {
        ledcWrite(buzzerPin, 128);
        delay(10);                // Ses süresi
        ledcWrite(buzzerPin, 0);  // Sesi kapat
        int r = (t_y - startY) / btnH;
        int c = (t_x - startX) / btnW;
        if (r >= 0 && r < 4 && c >= 0 && c < 3) {
          char k = numpad_keys[r][c];
          currentInput += k;
          updateScreen = true;
        }
      } else if (t_x >= ctrlX && t_x <= ctrlX + ctrlW) {
        if (t_y >= startY && t_y < startY + (totalH / 2)) {
          if (currentInput.length() > 0) {
            ledcWrite(buzzerPin, 255);
            delay(10);                // Ses süresi
            ledcWrite(buzzerPin, 0);  // Sesi kapat
            currentInput.remove(currentInput.length() - 1);
            updateScreen = true;
          }
        } else if (t_y >= startY + (totalH / 2) && t_y < startY + totalH) {
          finished = true;
          ledcWrite(buzzerPin, 255);
          delay(20);                  // Ses süresi
          ledcWrite(buzzerPin, 230);  // Sesi kapat
          delay(20);                  // Ses süresi
          ledcWrite(buzzerPin, 200);
          delay(20);                  // Ses süresi
          ledcWrite(buzzerPin, 190);  // Sesi kapat
          delay(20);                  // Ses süresi
          ledcWrite(buzzerPin, 150);  // Sesi kapat
          delay(20);                  // Ses süresi
          ledcWrite(buzzerPin, 130);
          delay(20);                // Ses süresi
          ledcWrite(buzzerPin, 0);  // Sesi kapat
        }
      }
    }
  }
  return currentInput;
}

// -------------------------------------------------------------------------
// SETUP
// -------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  // --- BELLEK AYIRMA ---
  // 75KB'lık alanı Heap'ten ayırıyoruz
  jpgBuffer = (uint8_t*)malloc(MAX_JPG_SIZE);
  // Buzzer pinini LEDC kanalına bağla (Bu ayarı normalde setup'ta yapmak daha iyidir
  // ama fonksiyonun tek başına çalışması için buraya ekledim)
  ledcAttach(buzzerPin, pwmFreq, pwmRes);
  preferences.begin("wifi_db", false);

  touchscreenSPI.begin(XPT2046_CLK, XPT2046_MISO, XPT2046_MOSI, XPT2046_CS);
  touchscreen.begin(touchscreenSPI);
  touchscreen.setRotation(1);

  tft.init();
  tft.setRotation(1);
  tft.fillScreen(TFT_WHITE);
  tft.setTextColor(TFT_BLACK, TFT_WHITE);

  TJpgDec.setJpgScale(1);
  TJpgDec.setSwapBytes(true);
  TJpgDec.setCallback(tft_output);

  int centerX = SCREEN_WIDTH / 2;
  typeWriterPrint("Sistem Baslatiliyor...", centerX, 100, FONT_SIZE);

  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  delay(1000);
}

// -------------------------------------------------------------------------
// LOOP
// -------------------------------------------------------------------------
void loop() {
  // AŞAMA 1: Wİ-Fİ BAĞLANTISI
  if (scan_wifi) {
    scan_wifi = false;
    tft.fillScreen(TFT_WHITE);
    tft.setTextColor(TFT_BLACK);
    typeWriterPrint("Wi-Fi Taraniyor...", SCREEN_WIDTH / 2, 110, 2);

    int n = WiFi.scanNetworks();
    if (n == 0) {
      tft.fillScreen(TFT_WHITE);
      typeWriterPrint("Ag Bulunamadi!", SCREEN_WIDTH / 2, 110, 2);
      delay(2000);
      scan_wifi = true;
    } else {
      bool agSecildi = false;
      for (int i = 0; i < n; ++i) {
        String currentSSID = WiFi.SSID(i);
        String encType = (WiFi.encryptionType(i) == WIFI_AUTH_OPEN) ? "ACIK" : "SIFRELI";
        printWifiInfo(currentSSID, String(WiFi.RSSI(i)), encType);
        unsigned long startWait = millis();
        while (millis() - startWait < 3000) {
          int progress = map(millis() - startWait, 0, 3000, 0, 320);
          tft.drawFastHLine(0, 230, progress, TFT_RED);
          if (touchscreen.tirqTouched() && touchscreen.touched()) {
            agSecildi = true;
            while (touchscreen.touched())
              ;
            String password = "";
            String key = ssidToKey(currentSSID);
            String savedPass = preferences.getString(key.c_str(), "");
            if (encType != "ACIK" && savedPass == "") password = getPasswordFromKeyboard(currentSSID, savedPass);
            tft.fillScreen(TFT_BLACK);
            tft.setTextColor(TFT_WHITE);
            typeWriterPrint("Baglaniyor...", SCREEN_WIDTH / 2, 100, 2);
            typeWriterPrint(currentSSID, SCREEN_WIDTH / 2, 130, 2);
            if (savedPass != "") WiFi.begin(currentSSID.c_str(), savedPass.c_str());
            else WiFi.begin(currentSSID.c_str(), password.c_str());
            int timeout = 0;
            while (WiFi.status() != WL_CONNECTED && timeout < 20) {
              delay(500);
              timeout++;
            }
            if (WiFi.status() == WL_CONNECTED) {
              if (encType != "ACIK" && savedPass == "") preferences.putString(key.c_str(), password);
              tft.fillScreen(TFT_GREEN);
              tft.setTextColor(TFT_BLACK);
              typeWriterPrint("Wi-Fi BAGLANDI!", SCREEN_WIDTH / 2, 100, 2);
              delay(1000);
              i = n;
            } else {
              preferences.remove(key.c_str());
              tft.fillScreen(TFT_RED);
              tft.setTextColor(TFT_WHITE);
              typeWriterPrint("SIFRE HATALI - SILINDI", SCREEN_WIDTH / 2, 110, 2);
              delay(2000);
              scan_wifi = true;
            }
            break;
          }
        }
        if (agSecildi) break;
      }
      if (!agSecildi && WiFi.status() != WL_CONNECTED) scan_wifi = true;
    }
  }

  // AŞAMA 2: BAĞLANTI SONRASI
  if (WiFi.status() == WL_CONNECTED) {
    if (!isStarted) {
      String savedIP = preferences.getString("target_ip", "");
      targetIP = getIPPortFromNumpad(savedIP);
      if (targetIP != "" && targetIP != savedIP) preferences.putString("target_ip", targetIP);
      isStarted = true;
      tft.fillScreen(TFT_BLACK);
    }else {
      // ============================================================
      // SÜREKLİ AKIŞ MODU (CONTINUOUS STREAM - RECEIVER)
      // ============================================================

      if (!streamClient.connected()) {
        int colonIndex = targetIP.indexOf(':');
        String ipStr = targetIP.substring(0, colonIndex);
        int port = targetIP.substring(colonIndex + 1).toInt();

        if (!streamClient.connect(ipStr.c_str(), port)) {
          delay(100);
          return;
        }
        // Nagle algoritmasını kapatır (Daha düşük gecikme sağlar)
        streamClient.setNoDelay(true);
      }

      // 1. HEADER KONTROLÜ (4 Byte gelmiş mi?)
      // Python sürekli veri gönderiyor. Eğer buffer boşsa, 
      // işlemciyi bloklamadan loop'un başına dönüyoruz.
      if (streamClient.available() < 4) {
        return; 
      }

      // 2. BOYUTU OKU
      uint8_t sizeBuffer[4];
      // readBytes, 4 byte gelene kadar bekler (varsayılan timeout süresince)
      if (streamClient.readBytes(sizeBuffer, 4) != 4) {
         return; // Eksik okuma olursa çık
      }
      
      uint32_t jpgSize = (sizeBuffer[0] << 24) | (sizeBuffer[1] << 16) | (sizeBuffer[2] << 8) | sizeBuffer[3];

      // 3. GÜVENLİK KONTROLÜ
      // Eğer gelen paket boyutu bufferımızdan büyükse veya 0 ise hata var demektir.
      if (jpgSize > MAX_JPG_SIZE || jpgSize == 0) {
        Serial.printf("Hatali Paket Boyutu: %u\n", jpgSize);
        // Senkronizasyon bozulmuş olabilir, buffer'ı temizle
        while (streamClient.available()) streamClient.read();
        streamClient.stop(); // Bağlantıyı yenilemek en güvenlisidir
        return;
      }

      // 4. RESİM VERİSİNİ OKU
      // Header'ı okuduk, şimdi gövdenin tamamının gelmesini bekleyeceğiz.
      // Burada timeout mekanizması kullanıyoruz.
      unsigned long startRead = millis();
      size_t readLen = 0;
      
      while (readLen < jpgSize) {
        // Veri varsa oku
        if (streamClient.available()) {
          int r = streamClient.read(jpgBuffer + readLen, jpgSize - readLen);
          if (r > 0) {
            readLen += r;
            startRead = millis(); // Her veri geldiğinde zamanlayıcıyı sıfırla
          }
        }
        
        // Timeout Kontrolü (1 saniye içinde paket tamamlanmazsa)
        if (millis() - startRead > 1000) {
          Serial.println("Timeout: Resim verisi yarim kaldi.");
          streamClient.stop();
          return;
        }
      }

      // 5. ÇİZ (TJpg_Decoder)
      // Veri tamamsa çizdiriyoruz.
      TJpgDec.drawJpg(0, 0, jpgBuffer, jpgSize);
      
      // FPS Hesabı (Serial Plotter için)
      Serial.println(millis() - timeDelay);
      timeDelay = millis();
    }
  }
}
