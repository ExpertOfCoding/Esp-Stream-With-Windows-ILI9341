import cv2
import socket
import struct
import time
import threading
import os
import mss
import numpy as np
import sys
import subprocess
import random  # <--- EKLENDİ: Rastgelelik için gerekli kütüphane

# --- OPEN ON PC ---
openonpc = True
openonpc_delay = 1  # Dosya açıldıktan sonra pencerenin gelmesi için bekleme süresi

# --- AYARLAR ---
VIDEO_PATH = "medya"  # 'screen', '0', veya dosya yolu 0
# 0 = kamera
# 'screen' = ekran paylaşımı
# 'video.mp4' = video dosyası
# 'medya' = klasör (içindeki tüm geçerli medya dosyalarını
PORT = 8080

# --- PERFORMANS VE AKIŞ AYARLARI ---
TARGET_FPS = 15
FRAME_TIME = 1.0 / TARGET_FPS

# --- SLAYT AYARLARI ---
# klasör seçerseniz her resim için 5 saniye, videolar kendi sürelerine göre gösterilir
SLIDE_INTERVAL = 5.0

# --- GÖRÜNTÜ İŞLEME AYARLARI ---
ENABLE_ROTATION = False
ENABLE_FIT_AND_FILL = True

# --- KALİTE AYARLARI ---
VIDEO_JPEG_QUALITY = 90
IMAGE_JPEG_QUALITY = 90

# --- GLOBAL DEĞİŞKENLER ---
global_frame = None
lock = threading.Lock()


def get_dominant_color(image):
    small = cv2.resize(image, (1, 1), interpolation=cv2.INTER_AREA)
    return small[0][0]


def process_frame(frame):
    if frame is None: return None
    h, w = frame.shape[:2]

    if ENABLE_ROTATION and h > w:
        frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        h, w = frame.shape[:2]

    target_w, target_h = 320, 240

    if ENABLE_FIT_AND_FILL:
        scale = min(target_w / w, target_h / h)
        new_w = int(w * scale)
        new_h = int(h * scale)
        resized_frame = cv2.resize(frame, (new_w, new_h))

        avg_color = get_dominant_color(resized_frame)
        canvas = np.zeros((target_h, target_w, 3), dtype=np.uint8)
        canvas[:] = avg_color

        x_offset = (target_w - new_w) // 2
        y_offset = (target_h - new_h) // 2
        canvas[y_offset:y_offset + new_h, x_offset:x_offset + new_w] = resized_frame
        return canvas
    else:
        return cv2.resize(frame, (target_w, target_h))


def camera_thread_func():
    global global_frame
    src = int(VIDEO_PATH)
    cap = cv2.VideoCapture(src)
    if VIDEO_PATH.isdigit():
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 30)

    while True:
        ret, frame = cap.read()
        if ret:
            with lock:
                global_frame = frame
        else:
            cap.release()
            time.sleep(1)
            cap = cv2.VideoCapture(src)
        time.sleep(0.01)


def screen_thread_func():
    global global_frame
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        while True:
            img = np.array(sct.grab(monitor))
            frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            with lock: global_frame = frame
            time.sleep(0.01)


def get_files_in_directory(path):
    valid_extensions = ('.jpg', '.jpeg', '.png', '.bmp', '.mp4', '.avi', '.mov', '.mkv')
    files = []
    try:
        for f in os.listdir(path):
            if f.lower().endswith(valid_extensions):
                files.append(os.path.join(path, f))
        files.sort()  # Başlangıçta alfabetik sırala, aşağıda karıştıracağız
    except Exception as e:
        print(f"Klasör hatası: {e}")
    return files


# --- YARDIMCI FONKSİYON: DOSYA AÇMA (Düzeltilmiş - Non-Blocking) ---
def open_media_on_pc(file_path):
    """Belirtilen dosyayı işletim sisteminin varsayılan oynatıcısıyla açar (Arka Planda)."""
    if not openonpc:
        return

    def _open_task():
        try:
            abs_path = os.path.abspath(file_path)
            # print(f"Dosya PC'de açılıyor: {abs_path}") # Konsolu kirletmemesi için kapattım

            if sys.platform == 'win32':
                os.startfile(abs_path)
            elif sys.platform == 'darwin':  # macOS
                subprocess.call(('open', abs_path))
            else:  # Linux
                subprocess.call(('xdg-open', abs_path))

            # Bekleme süresi artık sadece bu thread'i etkiler, veri akışını durdurmaz
            time.sleep(openonpc_delay)
        except Exception as e:
            print(f"Dosya açma hatası: {e}")

    # Dosya açma işlemini ayrı bir thread'de başlat
    threading.Thread(target=_open_task, daemon=True).start()

def start_server():
    global global_frame
    mode = "VIDEO"
    slide_files = []

    if VIDEO_PATH == "screen":
        mode = "SCREEN"
        threading.Thread(target=screen_thread_func, daemon=True).start()
    elif VIDEO_PATH.isdigit():
        mode = "CAMERA"
        threading.Thread(target=camera_thread_func, daemon=True).start()
    elif os.path.isdir(VIDEO_PATH):
        mode = "SLIDE"
        slide_files = get_files_in_directory(VIDEO_PATH)
        if not slide_files: return

        # --- RASGELE ÇALMA BAŞLANGICI ---
        # İlk başta listeyi bir kere karıştıralım
        print(f"Toplam dosya sayısı: {len(slide_files)}. Liste karıştırılıyor...")
        random.shuffle(slide_files)
        # --------------------------------

    elif os.path.exists(VIDEO_PATH) and VIDEO_PATH.lower().endswith(('.jpg', '.png', '.jpeg')):
        mode = "IMAGE"
    elif os.path.exists(VIDEO_PATH):
        mode = "VIDEO"
    else:
        print("Geçersiz VIDEO_PATH veya dosya bulunamadı.")
        return

    if mode in ["CAMERA", "SCREEN"]:
        while global_frame is None: time.sleep(0.1)

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 16384)

    try:
        server_socket.bind(('0.0.0.0', PORT))
        server_socket.listen(1)
    except OSError:
        print(f"Port {PORT} dolu.")
        return

    hostname = socket.gethostname()
    print(f"Server: {socket.gethostbyname(hostname)}:{PORT} | Mod: {mode}")

    static_data = None
    if mode == "IMAGE":
        open_media_on_pc(VIDEO_PATH)
        img = process_frame(cv2.imread(VIDEO_PATH))
        _, enc = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), IMAGE_JPEG_QUALITY])
        static_data = enc.tobytes()

    while True:
        print("\n--- ESP32 Bekleniyor ---")
        client_socket, addr = server_socket.accept()
        print(f"Bağlandı: {addr}")
        client_socket.settimeout(None)

        cap = None
        source_fps = 30
        start_time = time.time()
        current_frame_num = 0
        slide_index = 0
        slide_loaded = False
        slide_type = None
        slide_start_time = 0
        current_slide_img_data = None

        if mode == "VIDEO":
            open_media_on_pc(VIDEO_PATH)
            cap = cv2.VideoCapture(VIDEO_PATH)
            source_fps = cap.get(cv2.CAP_PROP_FPS) or 30
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            start_time = time.time()

        try:
            while True:
                loop_start_time = time.time()
                data_to_send = None

                while data_to_send is None:
                    if mode == "IMAGE":
                        data_to_send = static_data

                    elif mode in ["CAMERA", "SCREEN"]:
                        with lock:
                            if global_frame is not None:
                                frm = process_frame(global_frame.copy())
                                _, enc = cv2.imencode('.jpg', frm, [int(cv2.IMWRITE_JPEG_QUALITY), VIDEO_JPEG_QUALITY])
                                data_to_send = enc.tobytes()
                        if data_to_send is None: time.sleep(0.005)

                    elif mode == "VIDEO":
                        elapsed = time.time() - start_time
                        target_frame = int(elapsed * source_fps)

                        if target_frame >= total_frames:
                            start_time = time.time()
                            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                            current_frame_num = 0
                            target_frame = 0
                            open_media_on_pc(VIDEO_PATH)

                        while current_frame_num < target_frame:
                            cap.grab()
                            current_frame_num += 1

                        ret, frame = cap.read()
                        if not ret:
                            start_time = time.time()
                            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                            current_frame_num = 0
                            open_media_on_pc(VIDEO_PATH)
                            continue

                        current_frame_num += 1
                        frame = process_frame(frame)
                        _, enc = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), VIDEO_JPEG_QUALITY])
                        data_to_send = enc.tobytes()

                    elif mode == "SLIDE":
                        # Dosya yükleme kısmı
                        if not slide_loaded:
                            curr_file = slide_files[slide_index]
                            open_media_on_pc(curr_file)

                            ext = os.path.splitext(curr_file)[1].lower()
                            if ext in ['.mp4', '.avi', '.mov', '.mkv']:
                                slide_type = 'vid'
                                if cap: cap.release()
                                cap = cv2.VideoCapture(curr_file)
                                source_fps = cap.get(cv2.CAP_PROP_FPS) or 30
                                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                                start_time = time.time()
                                current_frame_num = 0
                            else:
                                slide_type = 'img'
                                if cap: cap.release()
                                cap = None
                                img = cv2.imread(curr_file)
                                if img is None:
                                    # Dosya bozuksa bir sonraki dosyaya geç (Random mantığı burada da işlemeli)
                                    slide_index += 1
                                    if slide_index >= len(slide_files):
                                        slide_index = 0
                                        print("--- Liste bitti, yeniden karıştırılıyor ---")
                                        random.shuffle(slide_files)
                                    continue
                                img = process_frame(img)
                                _, enc = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), IMAGE_JPEG_QUALITY])
                                current_slide_img_data = enc.tobytes()
                                slide_start_time = time.time()
                            slide_loaded = True

                        # Oynatma kısmı
                        if slide_type == 'img':
                            data_to_send = current_slide_img_data
                            # Resim süresi doldu mu?
                            if time.time() - slide_start_time > SLIDE_INTERVAL:
                                slide_index += 1
                                # Liste sonuna geldik mi?
                                if slide_index >= len(slide_files):
                                    slide_index = 0
                                    print("--- Liste bitti, yeniden karıştırılıyor ---")
                                    random.shuffle(slide_files)
                                slide_loaded = False

                        elif slide_type == 'vid':
                            elapsed = time.time() - start_time
                            target_frame = int(elapsed * source_fps)

                            # Video bitti mi (frame sayısına göre)?
                            if target_frame >= total_frames:
                                slide_index += 1
                                if slide_index >= len(slide_files):
                                    slide_index = 0
                                    print("--- Liste bitti, yeniden karıştırılıyor ---")
                                    random.shuffle(slide_files)
                                slide_loaded = False
                                continue

                            while current_frame_num < target_frame:
                                cap.grab()
                                current_frame_num += 1
                            ret, frame = cap.read()

                            # Video okuma hatası veya bitişi?
                            if not ret:
                                slide_index += 1
                                if slide_index >= len(slide_files):
                                    slide_index = 0
                                    print("--- Liste bitti, yeniden karıştırılıyor ---")
                                    random.shuffle(slide_files)
                                slide_loaded = False
                                continue

                            current_frame_num += 1
                            frame = process_frame(frame)
                            _, enc = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), VIDEO_JPEG_QUALITY])
                            data_to_send = enc.tobytes()

                # --- GÖNDERME ---
                try:
                    client_socket.sendall(struct.pack(">L", len(data_to_send)) + data_to_send)
                except socket.error:
                    print("Gönderme hatası, istemci koptu.")
                    break

                # --- FPS LİMİTLEME ---
                process_duration = time.time() - loop_start_time
                sleep_time = FRAME_TIME - process_duration
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except Exception as e:
            print(f"Hata: {e}")
        finally:
            if client_socket: client_socket.close()
            if cap: cap.release()


if __name__ == "__main__":
    start_server()
