// ============================================================
// GREEN CAM — Firmware ESP32-CAM
// Basé sur CameraWebServer officiel, étendu pour l'intégration GREEN.
//
// Endpoints exposés :
//   GET /stream   — flux MJPEG continu
//   GET /capture  — capture JPEG unique
//   GET /status   — état JSON (device, uptime, RSSI…)
//   GET /info     — infos réseau détaillées (MAC, IP, RSSI, modèle)
//
// Découverte : mDNS → http://green-cam.local
//
// Flasher avec :
//   Board      : AI Thinker ESP32-CAM
//   Partition  : Huge APP (3MB No OTA)
//   Upload speed: 115200
// ============================================================

#include "esp_camera.h"
#include "esp_http_server.h"
#include "esp_timer.h"
#include <WiFi.h>
#include <ESPmDNS.h>

// ---- Configuration -----------------------------------------
// Modifier ces valeurs sans toucher au reste du code.

#define CAM_DEVICE_NAME   "GREEN-CAM-01"
#define CAM_FIRMWARE_VER  "1.0.0"

// Wi-Fi — peut aussi être chargé depuis NVS/SPIFFS en v2
#define WIFI_SSID         "HUBNUXUSLAB"
#define WIFI_PASSWORD     "Hubnexus@2026"

// Résolution par défaut (FRAMESIZE_VGA = 640×480)
// Options : FRAMESIZE_QVGA, FRAMESIZE_VGA, FRAMESIZE_SVGA, FRAMESIZE_XGA, FRAMESIZE_UXGA
#define CAM_FRAME_SIZE    FRAMESIZE_VGA

// Qualité JPEG : 0 (max) → 63 (min). Recommandé : 10–20.
#define CAM_JPEG_QUALITY  12

// ---- Pinout AI Thinker ESP32-CAM ---------------------------
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

// ---- Globals -----------------------------------------------
static httpd_handle_t _server = NULL;
static uint32_t       _boot_ms = 0;

// ============================================================
// Wi-Fi
// ============================================================
void wifi_connect() {
  Serial.printf("[WiFi] Connexion à %s…\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  uint8_t attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print('.');
    attempts++;
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("[WiFi] Connecté — IP : %s\n", WiFi.localIP().toString().c_str());
    Serial.printf("[WiFi] RSSI : %d dBm\n", WiFi.RSSI());
  } else {
    Serial.println("[WiFi] ERREUR : échec de connexion. Redémarrage dans 5 s…");
    delay(5000);
    ESP.restart();
  }
}

// ============================================================
// Caméra
// ============================================================
bool camera_init() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0       = Y2_GPIO_NUM;
  config.pin_d1       = Y3_GPIO_NUM;
  config.pin_d2       = Y4_GPIO_NUM;
  config.pin_d3       = Y5_GPIO_NUM;
  config.pin_d4       = Y6_GPIO_NUM;
  config.pin_d5       = Y7_GPIO_NUM;
  config.pin_d6       = Y8_GPIO_NUM;
  config.pin_d7       = Y9_GPIO_NUM;
  config.pin_xclk     = XCLK_GPIO_NUM;
  config.pin_pclk     = PCLK_GPIO_NUM;
  config.pin_vsync    = VSYNC_GPIO_NUM;
  config.pin_href     = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn     = PWDN_GPIO_NUM;
  config.pin_reset    = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  // Utilise PSRAM si disponible pour les grandes résolutions
  if (psramFound()) {
    config.frame_size   = CAM_FRAME_SIZE;
    config.jpeg_quality = CAM_JPEG_QUALITY;
    config.fb_count     = 2;       // double-buffering pour la fluidité
    config.fb_location  = CAMERA_FB_IN_PSRAM;
    config.grab_mode    = CAMERA_GRAB_LATEST;
  } else {
    // Sans PSRAM : résolution réduite obligatoire
    config.frame_size   = FRAMESIZE_SVGA;
    config.jpeg_quality = 15;
    config.fb_count     = 1;
    config.fb_location  = CAMERA_FB_IN_DRAM;
    config.grab_mode    = CAMERA_GRAB_WHEN_EMPTY;
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("[CAM] Erreur init : 0x%x\n", err);
    return false;
  }

  // Ajustements capteur pour une meilleure image en extérieur
  sensor_t *s = esp_camera_sensor_get();
  if (s) {
    s->set_brightness(s, 0);
    s->set_contrast(s, 0);
    s->set_saturation(s, 0);
    s->set_special_effect(s, 0);  // aucun effet
    s->set_whitebal(s, 1);        // balance des blancs auto
    s->set_awb_gain(s, 1);
    s->set_wb_mode(s, 0);         // auto
    s->set_exposure_ctrl(s, 1);   // exposition auto
    s->set_aec2(s, 0);
    s->set_gain_ctrl(s, 1);       // gain auto
    s->set_agc_gain(s, 0);
    s->set_gainceiling(s, (gainceiling_t)0);
    s->set_bpc(s, 0);
    s->set_wpc(s, 1);
    s->set_raw_gma(s, 1);
    s->set_lenc(s, 1);
    s->set_hmirror(s, 0);
    s->set_vflip(s, 0);
    s->set_dcw(s, 1);
    s->set_colorbar(s, 0);
  }

  Serial.println("[CAM] Initialisée avec succès.");
  return true;
}

// ============================================================
// Handlers HTTP
// ============================================================

// ---- /stream ------------------------------------------------
// Flux MJPEG — compatible avec le navigateur et httpx (backend).
#define PART_BOUNDARY "123456789000000000000987654321"
static const char* _STREAM_CONTENT_TYPE =
  "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char* _STREAM_BOUNDARY     = "\r\n--" PART_BOUNDARY "\r\n";
static const char* _STREAM_PART        =
  "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

static esp_err_t stream_handler(httpd_req_t *req) {
  camera_fb_t *fb = NULL;
  esp_err_t    res = ESP_OK;
  char         part_buf[64];

  res = httpd_resp_set_type(req, _STREAM_CONTENT_TYPE);
  if (res != ESP_OK) return res;

  // Désactive Nagle pour réduire la latence
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  httpd_resp_set_hdr(req, "X-Framerate", "25");

  while (true) {
    fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("[CAM] Échec capture frame");
      res = ESP_FAIL;
      break;
    }

    // En-tête de partie MJPEG
    res = httpd_resp_send_chunk(req, _STREAM_BOUNDARY, strlen(_STREAM_BOUNDARY));
    if (res == ESP_OK) {
      size_t hlen = snprintf(part_buf, sizeof(part_buf), _STREAM_PART, fb->len);
      res = httpd_resp_send_chunk(req, part_buf, hlen);
    }
    if (res == ESP_OK) {
      res = httpd_resp_send_chunk(req, (const char *)fb->buf, fb->len);
    }

    esp_camera_fb_return(fb);

    if (res != ESP_OK) break;
  }

  return res;
}

// ---- /capture -----------------------------------------------
// Retourne un JPEG unique — utilisé par le backend pour le grab de frame.
static esp_err_t capture_handler(httpd_req_t *req) {
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    httpd_resp_send_500(req);
    return ESP_FAIL;
  }

  httpd_resp_set_type(req, "image/jpeg");
  httpd_resp_set_hdr(req, "Content-Disposition", "inline; filename=capture.jpg");
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");

  esp_err_t res = httpd_resp_send(req, (const char *)fb->buf, fb->len);
  esp_camera_fb_return(fb);
  return res;
}

// ---- /status ------------------------------------------------
// État machine pour la découverte backend.
static esp_err_t status_handler(httpd_req_t *req) {
  uint32_t uptime_s = (millis() - _boot_ms) / 1000;
  int      rssi     = WiFi.RSSI();

  char buf[512];
  snprintf(buf, sizeof(buf),
    "{"
    "\"device\":\"%s\","
    "\"status\":\"online\","
    "\"firmware\":\"%s\","
    "\"camera\":true,"
    "\"stream\":\"/stream\","
    "\"capture\":\"/capture\","
    "\"uptime\":%lu,"
    "\"rssi\":%d,"
    "\"ip\":\"%s\""
    "}",
    CAM_DEVICE_NAME,
    CAM_FIRMWARE_VER,
    (unsigned long)uptime_s,
    rssi,
    WiFi.localIP().toString().c_str()
  );

  httpd_resp_set_type(req, "application/json");
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  return httpd_resp_sendstr(req, buf);
}

// ---- /info --------------------------------------------------
// Informations réseau détaillées.
static esp_err_t info_handler(httpd_req_t *req) {
  uint8_t mac[6];
  WiFi.macAddress(mac);
  char mac_str[18];
  snprintf(mac_str, sizeof(mac_str), "%02X:%02X:%02X:%02X:%02X:%02X",
           mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);

  char buf[512];
  snprintf(buf, sizeof(buf),
    "{"
    "\"device\":\"%s\","
    "\"model\":\"ESP32-CAM (AI Thinker)\","
    "\"firmware\":\"%s\","
    "\"mac\":\"%s\","
    "\"ip\":\"%s\","
    "\"gateway\":\"%s\","
    "\"rssi\":%d,"
    "\"channel\":%d,"
    "\"ssid\":\"%s\","
    "\"free_heap\":%lu,"
    "\"psram\":%s"
    "}",
    CAM_DEVICE_NAME,
    CAM_FIRMWARE_VER,
    mac_str,
    WiFi.localIP().toString().c_str(),
    WiFi.gatewayIP().toString().c_str(),
    WiFi.RSSI(),
    WiFi.channel(),
    WiFi.SSID().c_str(),
    (unsigned long)ESP.getFreeHeap(),
    psramFound() ? "true" : "false"
  );

  httpd_resp_set_type(req, "application/json");
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  return httpd_resp_sendstr(req, buf);
}

// ============================================================
// Serveur HTTP
// ============================================================
void start_server() {
  httpd_config_t config    = HTTPD_DEFAULT_CONFIG();
  config.server_port       = 80;
  config.max_uri_handlers  = 8;
  config.stack_size        = 8192;

  if (httpd_start(&_server, &config) != ESP_OK) {
    Serial.println("[HTTP] Erreur démarrage serveur");
    return;
  }

  // /stream
  httpd_uri_t stream_uri = {
    .uri       = "/stream",
    .method    = HTTP_GET,
    .handler   = stream_handler,
    .user_ctx  = NULL
  };
  httpd_register_uri_handler(_server, &stream_uri);

  // /capture
  httpd_uri_t capture_uri = {
    .uri       = "/capture",
    .method    = HTTP_GET,
    .handler   = capture_handler,
    .user_ctx  = NULL
  };
  httpd_register_uri_handler(_server, &capture_uri);

  // /status
  httpd_uri_t status_uri = {
    .uri       = "/status",
    .method    = HTTP_GET,
    .handler   = status_handler,
    .user_ctx  = NULL
  };
  httpd_register_uri_handler(_server, &status_uri);

  // /info
  httpd_uri_t info_uri = {
    .uri       = "/info",
    .method    = HTTP_GET,
    .handler   = info_handler,
    .user_ctx  = NULL
  };
  httpd_register_uri_handler(_server, &info_uri);

  Serial.printf("[HTTP] Serveur démarré sur port %d\n", config.server_port);
}

// ============================================================
// mDNS — découverte automatique sans IP fixe
// ============================================================
void mdns_start() {
  // Le backend découvrira l'ESP32 via http://green-cam.local/status
  if (!MDNS.begin("green-cam")) {
    Serial.println("[mDNS] Erreur — découverte automatique indisponible");
    return;
  }
  // Service HTTP pour la découverte programmatique
  MDNS.addService("http",   "tcp", 80);
  MDNS.addService("green",  "tcp", 80);   // service propriétaire GREEN
  MDNS.addServiceTxt("green", "tcp", "device",   CAM_DEVICE_NAME);
  MDNS.addServiceTxt("green", "tcp", "firmware", CAM_FIRMWARE_VER);
  MDNS.addServiceTxt("green", "tcp", "stream",   "/stream");
  Serial.println("[mDNS] Actif — accessible via http://green-cam.local");
}

// ============================================================
// Wi-Fi reconnexion automatique (appelé dans loop)
// ============================================================
void check_wifi_reconnect() {
  static uint32_t _last_check = 0;
  if (millis() - _last_check < 10000) return;   // vérifie toutes les 10 s
  _last_check = millis();

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[WiFi] Connexion perdue — tentative de reconnexion…");
    WiFi.disconnect();
    WiFi.reconnect();
    uint8_t tries = 0;
    while (WiFi.status() != WL_CONNECTED && tries < 20) {
      delay(500);
      tries++;
    }
    if (WiFi.status() == WL_CONNECTED) {
      Serial.printf("[WiFi] Reconnecté — IP : %s\n", WiFi.localIP().toString().c_str());
      // Le serveur HTTP reste actif — pas besoin de le redémarrer
    } else {
      Serial.println("[WiFi] Reconnexion échouée — prochain essai dans 10 s");
    }
  }
}

// ============================================================
// Setup + Loop
// ============================================================
void setup() {
  Serial.begin(115200);
  Serial.setDebugOutput(false);
  Serial.println("\n[GREEN CAM] Démarrage firmware " CAM_FIRMWARE_VER);

  _boot_ms = millis();

  // 1. Caméra
  if (!camera_init()) {
    Serial.println("[FATAL] Caméra non initialisée — arrêt.");
    while (true) delay(1000);
  }

  // 2. Wi-Fi
  wifi_connect();

  // 3. mDNS
  mdns_start();

  // 4. Serveur HTTP
  start_server();

  Serial.println("[GREEN CAM] Prêt.");
  Serial.printf("  Stream  : http://%s/stream\n",  WiFi.localIP().toString().c_str());
  Serial.printf("  Capture : http://%s/capture\n", WiFi.localIP().toString().c_str());
  Serial.printf("  Status  : http://%s/status\n",  WiFi.localIP().toString().c_str());
  Serial.printf("  mDNS    : http://green-cam.local\n");
}

void loop() {
  // Seule tâche active dans loop : surveiller la connexion Wi-Fi
  check_wifi_reconnect();
  delay(100);
}
