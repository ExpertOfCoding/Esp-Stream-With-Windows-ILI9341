/*  
    ESP32 Smooth Video Stream Client (Fixed: Watchdog Error & Optimized)
    NOTES: NetworkTas 1 Works perfect
    esp should stay close to wifi otherwise it seems laggy
    screen stream optimised
*/

#include <SPI.h>
#include <FS.h>
#include <TFT_eSPI.h>
#include <WiFi.h>
#include <XPT2046_Touchscreen.h>
#include <Preferences.h>
#include <JPEGDEC.h>
#include <esp_task_wdt.h>  // Watchdog kütüphanesi eklendi

TFT_eSPI tft = TFT_eSPI();
Preferences preferences;
JPEGDEC jpeg;

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

#define CLIENT_TIMEOUT 1500
int pwmFreq = 2000;
int pwmRes = 8;

// --- GLOBAL DEĞİŞKENLER & BUFFER ---
unsigned long timeDelay = 0;
bool scan_wifi = true;
bool isStarted = false;
String targetIP = "";

int selectedMode = 0;  // 0: Seçilmedi, 1: SCREEN, 2: STREAM

// --- MULTI-THREADING YAPISI ---
TaskHandle_t Task1;
QueueHandle_t emptyQueue;
QueueHandle_t filledQueue;

struct JpgFrame {
  uint8_t* buffer;
  size_t len;
};

#define MAX_JPG_SIZE 50000

uint8_t* bufA;
uint8_t* bufB;

// --- KLAVYE & NUMPAD ---
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
  int randomDuty = random(1, 256);
  tft.setTextFont(fontIndex);
  int textWidth = tft.textWidth(text);
  int startX = centerX - (textWidth / 2);
  tft.setCursor(startX, y);

  for (int i = 0; i < text.length(); i++) {
    tft.print(text[i]);
    ledcWrite(buzzerPin, randomDuty);
    delay(10);
    ledcWrite(buzzerPin, 0);
    delay(35);
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

int JPEGDraw(JPEGDRAW* pDraw) {
  tft.pushImage(pDraw->x, pDraw->y, pDraw->iWidth, pDraw->iHeight, pDraw->pPixels);
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
          delay(10);
          ledcWrite(buzzerPin, 0);
          if (r == 2 && c == 9) {
            if (pass.length() > 0) pass.remove(pass.length() - 1);
          } else if (r == 3 && c == 9) {
            finish = true;
            ledcWrite(buzzerPin, 255);
            delay(20);
            ledcWrite(buzzerPin, 0);
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
        delay(10);
        ledcWrite(buzzerPin, 0);
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
            delay(10);
            ledcWrite(buzzerPin, 0);
            currentInput.remove(currentInput.length() - 1);
            updateScreen = true;
          }
        } else if (t_y >= startY + (totalH / 2) && t_y < startY + totalH) {
          finished = true;
          ledcWrite(buzzerPin, 255);
          delay(20);
          ledcWrite(buzzerPin, 0);
        }
      }
    }
  }
  return currentInput;
}

void drawModeButtons() {
  tft.fillScreen(TFT_BLACK);

  // Başlık
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.drawCentreString("MOD SECIMI", SCREEN_WIDTH / 2, 20, 2);

  // SCREEN Butonu (Sol - Mavi)
  tft.fillRect(20, 70, 130, 100, TFT_BLUE);
  tft.drawRect(20, 70, 130, 100, TFT_WHITE);
  tft.setTextColor(TFT_WHITE, TFT_BLUE);
  tft.drawCentreString("SCREEN", 85, 110, 2);

  // STREAM Butonu (Sağ - Turuncu)
  tft.fillRect(170, 70, 130, 100, TFT_ORANGE);
  tft.drawRect(170, 70, 130, 100, TFT_WHITE);
  tft.setTextColor(TFT_WHITE, TFT_ORANGE);
  tft.drawCentreString("STREAM", 235, 110, 2);
}


void NetworkTaskCode2(void* parameter) {
  WiFiClient localClient;
  String ipStr;
  int port;
  int colonIndex = targetIP.indexOf(':');
  ipStr = targetIP.substring(0, colonIndex);
  port = targetIP.substring(colonIndex + 1).toInt();
  while (true) {
    if (!localClient.connected()) {
      if (!localClient.connect(ipStr.c_str(), port)) {
        vTaskDelay(100 / portTICK_PERIOD_MS);
        continue;
      }
      localClient.setNoDelay(true);
    }
    if (localClient.available() < 4) {
      vTaskDelay(1 / portTICK_PERIOD_MS);
      continue;
    }

    uint8_t sizeBuffer[4];
    if (localClient.readBytes(sizeBuffer, 4) != 4) continue;
    uint32_t jpgSize = (sizeBuffer[0] << 24) | (sizeBuffer[1] << 16) | (sizeBuffer[2] << 8) | sizeBuffer[3];

    if (jpgSize > MAX_JPG_SIZE || jpgSize == 0) {
      while (localClient.available()) localClient.read();
      localClient.stop();
      continue;
    }

    uint8_t* ptr = NULL;
    if (xQueueReceive(emptyQueue, &ptr, portMAX_DELAY) == pdPASS) {

      size_t readLen = 0;
      unsigned long startRead = millis();
      bool error = false;

      while (readLen < jpgSize) {
        if (localClient.available()) {
          int r = localClient.read(ptr + readLen, jpgSize - readLen);
          if (r > 0) {
            readLen += r;
            startRead = millis();
          }
        }
        if (millis() - startRead > CLIENT_TIMEOUT) {
          localClient.stop();
          error = true;
          break;
        }
      }

      if (!error) {
        JpgFrame frame;
        frame.buffer = ptr;
        frame.len = jpgSize;
        xQueueSend(filledQueue, &frame, portMAX_DELAY);
      } else {
        xQueueSend(emptyQueue, &ptr, portMAX_DELAY);
      }
    }
  }
}

// ====================================================================================
// PERFORMANS ODAKLI NETWORK GÖREVİ (Smart Yielding)
// ====================================================================================
void NetworkTaskCode(void* parameter) {
  WiFiClient localClient;
  String ipStr;
  int port;

  int colonIndex = targetIP.indexOf(':');
  ipStr = targetIP.substring(0, colonIndex);
  port = targetIP.substring(colonIndex + 1).toInt();

  // Watchdog için zaman sayacı
  unsigned long lastYieldTime = 0;

  while (true) {
    if (!localClient.connected()) {
      if (!localClient.connect(ipStr.c_str(), port)) {
        // Bağlı değilken beklemesinde sakınca yok
        vTaskDelay(100 / portTICK_PERIOD_MS);
        continue;
      }
      localClient.setNoDelay(true);
    }

    // --- KRİTİK NOKTA 1: VERİ BEKLEME ---
    // Eğer hiç veri yoksa işlemciyi yorma, 1ms bekle.
    // Bu sadece akış kesildiğinde devreye girer, akış varken çalışmaz.
    if (localClient.available() < 4) {
      // Sadece çok uzun süre veri gelmezse bekle (Smart Yield)
      if (millis() - lastYieldTime > 10) {
        vTaskDelay(1);
        lastYieldTime = millis();
      }
      continue;
    }

    uint8_t sizeBuffer[4];
    if (localClient.readBytes(sizeBuffer, 4) != 4) continue;
    uint32_t jpgSize = (sizeBuffer[0] << 24) | (sizeBuffer[1] << 16) | (sizeBuffer[2] << 8) | sizeBuffer[3];

    if (jpgSize > MAX_JPG_SIZE || jpgSize == 0) {
      while (localClient.available()) localClient.read();
      localClient.stop();
      continue;
    }

    uint8_t* ptr = NULL;
    if (xQueueReceive(emptyQueue, &ptr, portMAX_DELAY) == pdPASS) {

      size_t readLen = 0;
      unsigned long startRead = millis();
      bool error = false;

      while (readLen < jpgSize) {
        int avail = localClient.available();

        if (avail > 0) {
          int bytesToRead = jpgSize - readLen;
          if (bytesToRead > avail) bytesToRead = avail;

          // Veriyi son sürat oku
          int r = localClient.read(ptr + readLen, bytesToRead);
          if (r > 0) {
            readLen += r;
            startRead = millis();
          }
        }

        // --- KRİTİK NOKTA 2: SMART YIELD ---
        // Her seferinde değil, sadece 20ms'de bir 1ms mola ver.
        // Bu, Watchdog'u (5 saniye süresi var) resetlemek için fazlasıyla yeterli
        // ama görüntüyü dondurmayacak kadar kısadır.
        if (millis() - lastYieldTime > 20) {
          vTaskDelay(1);  // İşletim sistemine "Ben buradayım" de
          lastYieldTime = millis();
        }

        // Timeout kontrolü
        if (millis() - startRead > CLIENT_TIMEOUT) {
          localClient.stop();
          error = true;
          break;
        }
      }

      if (!error) {
        JpgFrame frame;
        frame.buffer = ptr;
        frame.len = jpgSize;
        xQueueSend(filledQueue, &frame, portMAX_DELAY);
      } else {
        xQueueSend(emptyQueue, &ptr, portMAX_DELAY);
      }
    }
  }
}
// -------------------------------------------------------------------------
// SETUP
// -------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  ledcAttach(buzzerPin, pwmFreq, pwmRes);

  preferences.begin("wifi_db", false);

  if (psramFound()) {
    Serial.println("PSRAM bulundu, buffer PSRAM'e kuruluyor...");
    bufA = (uint8_t*)ps_malloc(MAX_JPG_SIZE);
    bufB = (uint8_t*)ps_malloc(MAX_JPG_SIZE);
  } else {
    Serial.println("PSRAM yok, standart RAM kullaniliyor...");
    bufA = (uint8_t*)malloc(MAX_JPG_SIZE);
    bufB = (uint8_t*)malloc(MAX_JPG_SIZE);
  }

  if (bufA == NULL || bufB == NULL) {
    Serial.printf("Yetersiz bellek! Gereken: %d byte. Mevcut Free Heap: %d\n", MAX_JPG_SIZE * 2, ESP.getFreeHeap());
    while (1) { delay(1000); }
  }

  emptyQueue = xQueueCreate(2, sizeof(uint8_t*));
  filledQueue = xQueueCreate(2, sizeof(JpgFrame));

  xQueueSend(emptyQueue, &bufA, portMAX_DELAY);
  xQueueSend(emptyQueue, &bufB, portMAX_DELAY);

  touchscreenSPI.begin(XPT2046_CLK, XPT2046_MISO, XPT2046_MOSI, XPT2046_CS);
  touchscreen.begin(touchscreenSPI);
  touchscreen.setRotation(1);

  tft.init();
  tft.setRotation(1);
  tft.fillScreen(TFT_WHITE);
  tft.setSwapBytes(true);
  tft.initDMA();
  tft.setTextColor(TFT_BLACK, TFT_WHITE);

  int centerX = SCREEN_WIDTH / 2;
  typeWriterPrint("Sistem Baslatiliyor...", centerX, 100, FONT_SIZE);

  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  delay(1000);
}

// -------------------------------------------------------------------------
// LOOP (MAIN THREAD - CORE 1: EKRAN ÇİZİM)
// -------------------------------------------------------------------------
void loop() {
  // AŞAMA 1: Wİ-Fİ AYARLARI (Arayüz)
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

  // AŞAMA 2: BAĞLANTI SONRASI & STREAM BAŞLATMA
  if (WiFi.status() == WL_CONNECTED) {

    // 2.1: MOD SEÇİMİ (HENÜZ SEÇİLMEDİYSE)
    if (selectedMode == 0) {
      drawModeButtons();
      bool modeSelected = false;
      while (!modeSelected) {
        if (touchscreen.tirqTouched() && touchscreen.touched()) {
          TS_Point p = touchscreen.getPoint();
          int t_x = map(p.x, TS_MINX, TS_MAXX, 0, SCREEN_WIDTH);
          int t_y = map(p.y, TS_MINY, TS_MAXY, 0, SCREEN_HEIGHT);

          delay(150);  // Debounce
          while (touchscreen.touched())
            ;  // Parmağın çekilmesini bekle

          // SCREEN Butonu Koordinatları (20,70) - (150, 170)
          if (t_x >= 20 && t_x <= 150 && t_y >= 70 && t_y <= 170) {
            selectedMode = 1;  // SCREEN
            ledcWrite(buzzerPin, 200);
            delay(50);
            ledcWrite(buzzerPin, 0);
            modeSelected = true;
          }
          // STREAM Butonu Koordinatları (170,70) - (300, 170)
          else if (t_x >= 170 && t_x <= 300 && t_y >= 70 && t_y <= 170) {
            selectedMode = 2;  // STREAM
            ledcWrite(buzzerPin, 200);
            delay(50);
            ledcWrite(buzzerPin, 0);
            modeSelected = true;
          }
        }
      }
    }

    // 2.2: IP GİRİŞİ VE GÖREV BAŞLATMA
    else if (!isStarted) {
      String savedIP = preferences.getString("target_ip", "");
      targetIP = getIPPortFromNumpad(savedIP);
      if (targetIP != "" && targetIP != savedIP) preferences.putString("target_ip", targetIP);

      isStarted = true;
      tft.fillScreen(TFT_BLACK);

      if (selectedMode == 1) {
        // SCREEN SEÇİLDİ -> NetworkTaskCode
        xTaskCreatePinnedToCore(
          NetworkTaskCode,
          "NetTask",
          8192,
          NULL,
          1,
          &Task1,
          0);  // Core 0
      } else if (selectedMode == 2) {
        // STREAM SEÇİLDİ -> NetworkTaskCode2
        xTaskCreatePinnedToCore(
          NetworkTaskCode2,
          "NetTask2",
          8192,
          NULL,
          1,
          &Task1,
          0);  // Core 0
      }

    } else {
      // ============================================================
      // 2.3: ÇİZİM DÖNGÜSÜ (CORE 1 - Consumer)
      // ============================================================
      JpgFrame currentFrame;

      if (xQueueReceive(filledQueue, &currentFrame, 0) == pdPASS) {
        if (jpeg.openRAM(currentFrame.buffer, currentFrame.len, JPEGDraw)) {
          jpeg.setPixelType(RGB565_LITTLE_ENDIAN);
          jpeg.decode(0, 0, 0);
          jpeg.close();
        }
        xQueueSend(emptyQueue, &currentFrame.buffer, portMAX_DELAY);
      }
    }
  }
}
