import sys
import os
import tkinter as tk
from tkinter import scrolledtext, ttk, messagebox
import json
import pyautogui
pyautogui.PAUSE = 0.035
import cv2
import numpy as np
import time
import pytesseract
import logging
import queue
from threading import Thread
from functools import lru_cache
from pynput import keyboard
import pyuac

# 配置日志
logging.basicConfig(filename='app.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# 全局变量
enable_time_log = False  # 耗时日志开关
is_running = False
loop_thread = None
valid_cards = []
delays = {}
consecutive_failure_count = 0
consecutive_long_digit_count = 0  # 新增：连续长数字计数器
config = {}
log_queue = queue.Queue()
click_counter = 0

# UI输入变量
max_price_var = None
delay_stable_var = None
delay_buy_var = None
mode_var = None
USER_SETTINGS_FILE = 'user_settings.json'

# 屏幕分辨率
SCREEN_WIDTH, SCREEN_HEIGHT = 1920, 1080

# 简化日志调用
def log(message):
    """简化日志调用，确保所有日志都进入队列"""
    logging.info(message)
    print(message)  # 同时打印到控制台方便调试
    
    # 将日志放入队列供UI显示
    if 'log_queue' in globals() and log_queue:
        log_queue.put(message)

# 设置Tesseract环境
def setup_tesseract():
    try:
        if getattr(sys, 'frozen', False):
            # 打包后的环境 - 使用内置的tessdata
            base_path = sys._MEIPASS
            
            # 查找内置的Tesseract可执行文件
            tesseract_exe = os.path.join(base_path, 'tesseract.exe')
            tessdata_dir = os.path.join(base_path, 'tessdata')
            
            if os.path.exists(tesseract_exe) and os.path.exists(tessdata_dir):
                pytesseract.pytesseract.tesseract_cmd = tesseract_exe
                os.environ['TESSDATA_PREFIX'] = tessdata_dir
                log(f"使用内置Tesseract: {tesseract_exe}")
                log(f"使用内置语言包: {tessdata_dir}")
                return True
            else:
                # 如果内置组件缺失，尝试使用系统安装的Tesseract
                log("警告: 内置Tesseract组件缺失，尝试使用系统安装的Tesseract")
        else:
            # 开发环境 - 使用真实路径
            dev_tessdata = r'C:\Program Files\Tesseract-OCR\tessdata'
            dev_tesseract = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
            
            if os.path.exists(dev_tesseract) and os.path.exists(dev_tessdata):
                pytesseract.pytesseract.tesseract_cmd = dev_tesseract
                os.environ['TESSDATA_PREFIX'] = dev_tessdata
                log(f"开发环境: 使用系统Tesseract - {dev_tesseract}")
                return True
        
        # 尝试查找系统安装的Tesseract
        possible_paths = [
            r'C:\Program Files\Tesseract-OCR\tesseract.exe',
            r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
            r'C:\Tesseract-OCR\tesseract.exe'
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                pytesseract.pytesseract.tesseract_cmd = path
                tessdata_path = os.path.join(os.path.dirname(path), 'tessdata')
                if os.path.exists(tessdata_path):
                    os.environ["TESSDATA_PREFIX"] = tessdata_path
                    log(f"使用系统Tesseract: {path}")
                    return True
        
        # 如果所有尝试都失败
        log("错误: 未找到Tesseract OCR引擎")
        messagebox.showerror("OCR错误", "未找到Tesseract OCR引擎，请安装或检查程序完整性")
        return False
    
    except Exception as e:
        log(f"配置Tesseract时出错: {str(e)}")
        return False

# 初始化OCR配置
if not setup_tesseract():
    log("OCR功能可能不可用")

@lru_cache(maxsize=1)
def load_config():
    """加载配置文件（仅加载一次）"""
    global config
    try:
        with open('keys.json', 'r', encoding='utf-8') as f:
            loaded_json = json.load(f)
            config = loaded_json 
            log(f"配置文件 keys.json 加载成功")
            return config
    except FileNotFoundError:
        log(f"[错误] 配置文件 keys.json 不存在")
        return {'cards_config': [], 'delays': {}}
    except json.JSONDecodeError:
        log(f"[错误] 配置文件 keys.json 格式错误")
        return {'cards_config': [], 'delays': {}}
    except Exception as e:
        log(f"[错误] 读取 keys.json 时发生未知错误: {str(e)}")
        return {'cards_config': [], 'delays': {}}

def load_user_settings():
    """加载用户设置（价格和延迟）"""
    try:
        with open(USER_SETTINGS_FILE, 'r', encoding='utf-8') as f:
            user_settings = json.load(f)
            log(f"用户配置文件 {USER_SETTINGS_FILE} 加载成功")
            return user_settings
    except FileNotFoundError:
        log(f"用户配置文件 {USER_SETTINGS_FILE} 不存在，将使用默认设置")
        return {}
    except json.JSONDecodeError:
        log(f"[错误] 用户配置文件 {USER_SETTINGS_FILE} 格式错误")
        return {}
    except Exception as e:
        log(f"[错误] 读取 {USER_SETTINGS_FILE} 时发生未知错误: {str(e)}")
        return {}

def init_config():
    """初始化配置，根据UI选择的模式筛选卡片，并获取延迟配置、用户价格"""
    global valid_cards, delays, config, max_price_var, mode_var
    config = load_config()  # 加载 keys.json
    user_settings = load_user_settings()  # 加载 user_settings.json

    cards_config = config.get('cards_config', []) # 从 keys.json 读取 cards_config

    # 根据UI选择的模式筛选卡片
    selected_mode_name = mode_var.get() if mode_var else "收藏第一位置"
    valid_cards = []
    current_card_settings = None
    
    # 查找当前模式的卡片配置
    for card in cards_config:
        if card.get('name') == selected_mode_name:
            valid_cards.append(card)
            current_card_settings = card # 保存当前选中模式的卡片配置
            break # 找到即停止
    
    if not valid_cards:
        log(f"警告: 在模式 '{selected_mode_name}' 下未找到有效的卡片配置。")
        # 创建默认配置避免崩溃
        current_card_settings = {
            "name": selected_mode_name,
            "position": (0.3016, 0.2324),
            "quantity_control_pos": (0.822, 0.796),
            "buy_button_pos": (0.822, 0.796),
            "price_region": (0.155, 0.15, 0.1, 0.05),
            "max_price": 35  # 只保留最高价格
        }
        valid_cards.append(current_card_settings)
        log(f"已为模式 '{selected_mode_name}' 创建默认配置")

    # 优先从 user_settings 加载延迟，否则从 keys.json, 再否则用硬编码默认值
    delays_from_keys = config.get('delays', {})
    delays = {
        'page_stable_delay': user_settings.get('page_stable_delay', delays_from_keys.get('page_stable_delay', 20)),
        'buy_page_wait_delay': user_settings.get('buy_page_wait_delay', delays_from_keys.get('buy_page_wait_delay', 50))
    }

    # 更新UI中的延迟设置
    if delay_stable_var:  # 确保UI元素已创建
        delay_stable_var.set(delays['page_stable_delay'])
    if delay_buy_var:
        delay_buy_var.set(delays['buy_page_wait_delay'])

    # 设置价格：优先从 user_settings, 其次从当前选中模式的卡片配置, 最后是硬编码默认值
    default_max_price_from_card = 35

    if current_card_settings:
        default_max_price_from_card = current_card_settings.get('max_price', 35)
    
    # 优先从 user_settings 加载当前模式的特定价格
    max_price_to_set = user_settings.get(f'{selected_mode_name}_max_price', default_max_price_from_card)

    if max_price_var:
        max_price_var.set(max_price_to_set)

    log(f"当前模式: {selected_mode_name}")
    log(f"当前延迟配置: 页面稳定={delays['page_stable_delay']}ms, 购买页等待={delays['buy_page_wait_delay']}ms")
    log(f"当前最高价格设置: {max_price_to_set}")

def percent_to_pixel(percent_tuple):
    """将百分比坐标转换为像素坐标"""
    return (
        int(percent_tuple[0] * SCREEN_WIDTH),
        int(percent_tuple[1] * SCREEN_HEIGHT)
    )

def get_price_region_px():
    """获取价格区域的像素坐标（根据当前选中的模式）"""
    if not valid_cards:
        return (0, 0, 0, 0)
    
    # 使用当前模式的配置
    card_config = valid_cards[0]
    price_region_percent = card_config.get('price_region', (0.155, 0.15, 0.1, 0.05))
    
    return (
        int(price_region_percent[0] * SCREEN_WIDTH),
        int(price_region_percent[1] * SCREEN_HEIGHT),
        int(price_region_percent[2] * SCREEN_WIDTH),
        int(price_region_percent[3] * SCREEN_HEIGHT)
    )

def get_card_price():
    """获取当前卡片价格（保留性能计时）"""
    global consecutive_failure_count, consecutive_long_digit_count, enable_time_log
    region_px = get_price_region_px()
    
    # 性能计时器
    total_start = time.time() if enable_time_log else None
    screenshot_time = 0
    process_time = 0
    ocr_time = 0
    
    try:
        # 截图
        screenshot_start = time.time() if enable_time_log else None
        screenshot = pyautogui.screenshot(region=region_px)
        if enable_time_log:
            screenshot_time = time.time() - screenshot_start
        
        screenshot_np = np.array(screenshot)
    except Exception as e:
        log(f"截图失败: {e}")
        consecutive_failure_count += 1
        try:
            pyautogui.press('esc')
        except:
            pass
        return None

    # 图像处理
    process_start = time.time() if enable_time_log else None
    try:
        # 图像预处理 (使用第二个脚本的优化参数)
        gray = cv2.cvtColor(screenshot_np, cv2.COLOR_RGB2GRAY)
        # 图像放大(上采样)以提高OCR识别率
        gray = cv2.resize(gray, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_LINEAR)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        _, binary = cv2.threshold(gray, 140, 255, cv2.THRESH_BINARY_INV)
        
        if enable_time_log:
            process_time = time.time() - process_start
    except Exception as e:
        log(f"图像处理失败: {e}")
        return None

    # OCR识别 (使用第二个脚本的优化参数)
    ocr_start = time.time() if enable_time_log else None
    try:
        # 使用第二个脚本的OCR配置参数
        text = pytesseract.image_to_string(binary, lang='eng', config="--psm 7 --oem 1 -c tessedit_char_whitelist=0123456789")
        if enable_time_log:
            ocr_time = time.time() - ocr_start
        
        raw_text = text.strip()
        
        # ====== 新增：处理长数字问题 ======
        if len(raw_text) > 4:  # 如果识别出5位或更多数字
            consecutive_long_digit_count += 1
            log(f"识别到长数字({len(raw_text)}位): {raw_text}，连续计数: {consecutive_long_digit_count}/3")
            
            # 连续三次出现长数字时才处理
            if consecutive_long_digit_count >= 3:
                # 根据蛋模式进行不同截断
                egg_mode = mode_var.get() if mode_var else '金蛋'
                # 根据蛋模式进行不同截断
                if egg_mode in ['金蛋', '紫蛋']:
                    truncated_text = raw_text[:4]  # 直接取前四位
                elif egg_mode == '肉蛋':
                    truncated_text = raw_text[:3]  # 取前三位
                else:
                    # 保留原始处理逻辑（如果有需要）
                    truncated_text = raw_text
                try:
                    price = int(truncated_text)
                    # 处理成功后重置计数器
                    consecutive_long_digit_count = 0
                    
                    if enable_time_log:
                        total_time = time.time() - total_start
                        log(f"价格截断处理成功: {price} (原始: {raw_text}) | 耗时: {total_time:.3f}s")
                    else:
                        log(f"价格截断处理成功: {price} (原始: {raw_text})")
                    
                    return price
                except ValueError:
                    # 截断后仍转换失败，继续正常流程
                    pass
            else:
                # 未达三次，按识别失败处理
                raise ValueError(f"长数字未达连续三次 ({raw_text})")
        else:
            # 正常长度数字，重置长数字计数器
            consecutive_long_digit_count = 0
            price = int(raw_text)
        # ====== 结束新增部分 ======
        
        # 输出性能日志（如果启用）
        if enable_time_log:
            total_time = time.time() - total_start
            log(f"价格识别成功: {price} | 耗时: {total_time:.3f}s (截图: {screenshot_time:.3f}s, 处理: {process_time:.3f}s, OCR: {ocr_time:.3f}s)")
        else:
            log(f"价格识别成功: {price}")
        
        return price
    except (ValueError, TypeError):
        consecutive_failure_count += 1
        if enable_time_log:
            ocr_time = time.time() - ocr_start if 'ocr_time' in locals() else 0
            total_time = time.time() - total_start
            log_failure = f"价格识别失败: '{raw_text}' | 耗时: {total_time:.3f}s (截图: {screenshot_time:.3f}s, 处理: {process_time:.3f}s, OCR: {ocr_time:.3f}s)"
            log(log_failure)
        else:
            log(f"价格识别失败: '{raw_text}'")
        return None
    except Exception as e:
        consecutive_failure_count += 1
        log(f"价格识别异常: {str(e)}")
        return None

def recognize_fenghuo_region():
    """识别特定区域是否包含'烽火地带'"""
    region_percent = (0.0698, 0.3037, 0.0458, 0.0232)
    region_px = (
        int(region_percent[0] * SCREEN_WIDTH),
        int(region_percent[1] * SCREEN_HEIGHT),
        int(region_percent[2] * SCREEN_WIDTH),
        int(region_percent[3] * SCREEN_HEIGHT)
    )
    try:
        screenshot = pyautogui.screenshot(region=region_px)
        screenshot_np = np.array(screenshot)
        gray = cv2.cvtColor(screenshot_np, cv2.COLOR_RGB2GRAY)
        # 图像放大(上采样)以提高OCR识别率
        gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        # 图像预处理：高斯模糊降噪
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        # 使用自适应阈值
        binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 8)
        
        # 形态学操作：腐蚀和膨胀以去除噪点和连接字符
        kernel = np.ones((3,3),np.uint8)
        binary = cv2.erode(binary, kernel, iterations = 2)
        binary = cv2.dilate(binary, kernel, iterations = 2)
        
        # 使用简体中文语言包进行OCR
        try:
            text = pytesseract.image_to_string(binary, lang='chi_sim', config='--psm 6')
            log(f"烽火地带识别结果: '{text.strip()}'")
            # 检查是否包含"烽火地带"中的任意字符
            return any(char in text.strip() for char in "烽火地带")
        except:
            log("烽火地带OCR识别失败")
            return False
    except Exception as e:
        log(f"烽火地带识别异常: {str(e)}")
        return False

def process_card(card_config):
    """处理单个卡片（保留性能计时）"""
    global is_running, click_counter, enable_time_log, consecutive_failure_count
    
    if not is_running:
        return False

    # 获取页面稳定延迟
    page_delay = delays.get('page_stable_delay', 20) / 1000.0
    
    # 获取UI设定的最高价格
    try:
        max_price_ui = int(max_price_var.get())
    except ValueError:
        log(f"[错误] 价格必须是数字！")
        return False
    
    if max_price_ui < 0:
        log(f"[错误] 价格不能为负数！")
        return False

    # 点击卡片位置
    try:
        position_percent = card_config.get('position', (0.3016, 0.2324))
        pos_px = percent_to_pixel(position_percent)
        
        # 记录点击开始时间
        click_start = time.time() if enable_time_log else None
        
        pyautogui.moveTo(pos_px[0], pos_px[1])
        pyautogui.click()
        
        # 计算点击耗时
        if enable_time_log:
            move_click_time = time.time() - click_start
            log(f"点击卡片位置耗时: {move_click_time:.3f}s")
        
        # 应用页面稳定延迟
        time.sleep(page_delay)
    except Exception as e:
        log(f"点击卡片 '{card_config.get('name')}' 位置失败: {e}")
        consecutive_failure_count += 1
        return False

    # 点击数量控制按钮
    if 'quantity_control_pos' in card_config:
        try:
            quantity_control_pos = card_config.get('quantity_control_pos')
            quantity_control_px = percent_to_pixel(quantity_control_pos)
            
            # 记录点击开始时间
            quantity_start = time.time() if enable_time_log else None
            
            pyautogui.moveTo(quantity_control_px[0], quantity_control_px[1])
            pyautogui.click()
            
            # 计算点击耗时
            if enable_time_log:
                quantity_time = time.time() - quantity_start
                log(f"点击数量控制耗时: {quantity_time:.3f}s")
        except Exception as e:
            log(f"点击卡片 '{card_config.get('name')}' 的数量控制按钮失败: {e}")
            # 即使数量控制失败，也尝试继续

    # 获取价格
    price = get_card_price()
    if price is None:
        try:
            pyautogui.press('esc')
        except:
            pass
        return False

    # 识别成功，重置连续失败计数器
    consecutive_failure_count = 0

    # 判断价格是否小于等于最高价格（新逻辑）
    if price <= max_price_ui:
        log(f"价格 {price} 小于等于设定最高价格 {max_price_ui}，执行购买")
    else:
        log(f"价格 {price} 高于设定最高价格 {max_price_ui}")
        try:
            pyautogui.press('esc')
        except:
            pass
        return False

    # 获取购买页等待延迟
    buy_delay = delays.get('buy_page_wait_delay', 30) / 1000.0
    time.sleep(buy_delay)

    # 点击购买按钮
    try:
        buy_pos = card_config.get('buy_button_pos', (0.822, 0.796))
        buy_pos_px = percent_to_pixel(buy_pos)
        
        # 记录购买操作开始时间
        buy_start = time.time() if enable_time_log else None
        
        pyautogui.moveTo(buy_pos_px[0], buy_pos_px[1])
        pyautogui.click()
        
        # 计算购买操作耗时
        if enable_time_log:
            buy_time = time.time() - buy_start
            log(f"购买操作耗时: {buy_time:.3f}s")
        
        click_counter += 1
        # 更新UI中的点击次数
        if root and root.winfo_exists():
            root.after(0, update_click_count)
    except Exception as e:
        log(f"点击卡片 '{card_config.get('name')}' 的购买按钮失败: {e}")
        return False

    # 尝试关闭购买成功后的弹窗或返回
    try:
        pyautogui.press('esc')
    except:
        pass

    return True

def handle_consecutive_failures():
    """处理连续失败情况（包括识别烽火地带）"""
    global consecutive_failure_count
    
    log("价格连续识别失败三次，执行返回操作")
    try:
        pyautogui.press('esc')
        time.sleep(0.1)
        pyautogui.press('esc')
        time.sleep(0.5)
    except Exception as e:
        log(f"执行返回操作失败: {e}")
    
    # 检查是否识别到"烽火地带"
    if recognize_fenghuo_region():
        time.sleep(0.3)
        log("识别到'烽火地带'，尝试点击坐标 (0.3693, 0.0528) 两次")
        target_pos_percent = (0.3693, 0.0528)
        target_pos_px = percent_to_pixel(target_pos_percent)
        try:
            pyautogui.moveTo(target_pos_px[0], target_pos_px[1])
            pyautogui.click()
            time.sleep(0.1)
            pyautogui.click()
            time.sleep(0.5)
        except Exception as e:
            log(f"点击交易行失败: {e}")
    else:
        log("未识别到'烽火地带'，将再次尝试识别")
    
    consecutive_failure_count = 0
    # 添加延迟避免立即重复识别
    time.sleep(0.5)

def loop_function():
    """高效循环函数（专注于当前模式）"""
    global is_running, consecutive_failure_count, enable_time_log
    
    if not valid_cards:
        log("没有有效的卡片配置")
        is_running = False
        # 更新状态显示
        if 'root' in globals() and root.winfo_exists():
            root.after(0, update_status, "没有有效卡片配置")
        return
    
    # 只处理当前选择的模式
    card_to_process = valid_cards[0]
    log(f"开始处理模式: {card_to_process.get('name')}")
    
    # 循环计数器（用于性能日志）
    loop_count = 0
    
    while is_running:
        # 记录循环开始时间
        loop_start = time.time() if enable_time_log else None
        
        loop_count += 1
        
        # 在处理卡片前检查连续失败次数
        if consecutive_failure_count >= 3:
            handle_consecutive_failures()
            continue  # 跳过当前卡片处理，直接进入下一次循环

        # 记录卡片处理开始时间
        card_start = time.time() if enable_time_log else None

        # 处理卡片
        process_card(card_to_process)
        
        # 记录卡片处理时间
        if enable_time_log:
            card_time = time.time() - card_start
            log(f"卡片处理总耗时: {card_time:.3f}s")
        
        # 记录循环时间
        if enable_time_log:
            loop_time = time.time() - loop_start
            log(f"完成第 {loop_count} 次循环 | 循环耗时: {loop_time:.3f}s")
        
        # 短暂延迟避免CPU占用过高
        if is_running:
            time.sleep(0.01)

def start_loop():
    """开始循环（在新线程中运行）"""
    global is_running, loop_thread, consecutive_failure_count, click_counter
    if is_running:
        log("循环已在运行中")
        return
    
    click_counter = 0
    # 保存UI中的参数到配置
    save_config_from_ui()
    # 初始化配置
    init_config()
    
    is_running = True
    consecutive_failure_count = 0
    log("循环已启动 (F9暂停/继续, F10停止)")
    # 更新状态显示
    root.after(0, update_status, "运行中")
    loop_thread = Thread(
        target=loop_function,
        daemon=True
    )
    loop_thread.start()

def stop_loop():
    """停止循环"""
    global is_running, consecutive_failure_count
    is_running = False
    consecutive_failure_count = 0
    click_counter = 0
    log(f"循环已停止")
    # 更新状态显示
    if 'root' in globals() and root.winfo_exists():
        root.after(0, update_status, "未运行")
        root.after(0, update_click_count) # 更新点击次数显示为0

def pause_loop():
    """暂停/继续循环"""
    global is_running
    if loop_thread and loop_thread.is_alive():
        is_running = not is_running
        status_text = "暂停中" if not is_running else "运行中"
        log_message = "暂停" if not is_running else "继续"
        log(f"循环已{log_message}")
        # 更新状态显示
        if 'root' in globals() and root.winfo_exists():
            root.after(0, update_status, status_text)
    elif not is_running and not (loop_thread and loop_thread.is_alive()):
        log("循环未启动，无法暂停/继续。请先按F8启动。")
    else:
        log("循环已结束，无法暂停/继续。请按F8重新启动。")

def save_config_from_ui():
    """从UI保存参数到配置 (keys.json 和 user_settings.json)"""
    global config, mode_var, max_price_var, delay_stable_var, delay_buy_var
    
    if not config:
        config = load_config()
        if not config:
             config = {"cards_config": [], "delays": {}}
    
    user_settings_to_save = {}
    selected_mode_name = mode_var.get() if mode_var else "收藏第一位置"

    # 1. 保存延迟配置
    try:
        page_delay = int(delay_stable_var.get())
        buy_delay = int(delay_buy_var.get())
        
        if 'delays' not in config:
            config['delays'] = {}
        config['delays']['page_stable_delay'] = page_delay
        config['delays']['buy_page_wait_delay'] = buy_delay
        
        user_settings_to_save['page_stable_delay'] = page_delay
        user_settings_to_save['buy_page_wait_delay'] = buy_delay
    except ValueError:
        log(f"[错误] 延迟值必须是数字！")
        messagebox.showerror("错误", "延迟值必须是数字！")
        return
    except TypeError:
        log(f"[错误] 内部配置错误 (delays)。")
        messagebox.showerror("错误", "内部配置错误 (delays)。")
        return

    # 2. 保存UI最高价格
    try:
        max_price_ui = int(max_price_var.get())

        if max_price_ui < 0:
            log(f"[错误] 价格不能为负数！")
            messagebox.showerror("错误", "价格不能为负数！")
            return

        user_settings_to_save[f'{selected_mode_name}_max_price'] = max_price_ui

    except ValueError:
        log(f"[错误] 价格必须是数字！")
        messagebox.showerror("错误", "价格必须是数字！")
        return
    except TypeError:
        log(f"[错误] 内部配置错误 (prices)。")
        messagebox.showerror("错误", "内部配置错误 (prices)。")
        return

    # 3. 保存到 keys.json 文件
    try:
        with open('keys.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        log("配置已保存到 keys.json")
    except Exception as e:
        log(f"保存配置到 keys.json 失败: {e}")
        messagebox.showerror("错误", f"保存配置到 keys.json 失败: {e}")
        return

    # 4. 保存到 user_settings.json 文件
    try:
        existing_user_settings = load_user_settings()
        existing_user_settings.update(user_settings_to_save)
        with open(USER_SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(existing_user_settings, f, ensure_ascii=False, indent=4)
        log(f"用户设置已保存到 {USER_SETTINGS_FILE}")
    except Exception as e:
        log(f"保存用户设置到 {USER_SETTINGS_FILE} 失败: {e}")
        messagebox.showerror("错误", f"保存用户设置到 {USER_SETTINGS_FILE} 失败: {e}")

def update_log_display():
    """定期从队列获取日志并更新UI"""
    while not log_queue.empty():
        message = log_queue.get()
        log_text.configure(state='normal')  # 允许编辑
        log_text.insert(tk.END, message + "\n")
        log_text.see(tk.END)  # 滚动到最新日志
        log_text.configure(state='disabled')  # 禁用编辑
    if 'root' in globals() and root.winfo_exists():
        root.after(100, update_log_display)  # 每100毫秒检查一次

def update_status(status):
    """更新状态显示"""
    if 'status_var' in globals():
        status_var.set(f"状态: {status}")

def update_click_count():
    """更新点击次数显示"""
    if 'click_count_var' in globals():
        click_count_var.set(f"本次运行共点击购买按钮 {click_counter} 次")

# 后台热键监听逻辑
def on_key_press(key):
    """后台捕获按键事件（不受窗口焦点影响）"""
    global is_running
    try:
        if key == keyboard.Key.f8:
            if not is_running:
                start_loop()
            else:
                log("循环已在运行中，无需重复启动 (F9暂停/继续, F10停止)")
        elif key == keyboard.Key.f9:
            pause_loop()
        elif key == keyboard.Key.f10:
            stop_loop()
    except AttributeError:
        pass  # 忽略特殊按键

class AppUI:
    def __init__(self, master):
        self.master = master
        global root, status_var, delay_stable_var, delay_buy_var, log_text, click_count_var, max_price_var, mode_var
        root = master

        master.title("屯仓抢金弹助手")
        master.geometry("700x550")
        master.minsize(650, 500)

        # 主框架
        main_frame = ttk.Frame(master, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # --- 左侧：参数设置 --- 
        params_labelframe = ttk.LabelFrame(left_frame, text="参数设置", padding=10)
        params_labelframe.pack(fill=tk.X)

        # 模式选择
        ttk.Label(params_labelframe, text="模式选择:").grid(row=0, column=0, sticky=tk.W, pady=5)
        mode_var = tk.StringVar(value="金蛋")
        mode_options = ["金蛋", "紫蛋", "肉蛋"] 
        mode_dropdown = ttk.Combobox(params_labelframe, textvariable=mode_var, values=mode_options, width=18, state="readonly")
        mode_dropdown.grid(row=0, column=1, sticky=tk.EW, pady=5, padx=5)
        mode_dropdown.bind("<<ComboboxSelected>>", self.on_mode_change)

        # 最高价格（移除了最低价格）
        ttk.Label(params_labelframe, text="最高价格:").grid(row=1, column=0, sticky=tk.W, pady=5)
        max_price_var = tk.StringVar()
        max_price_entry = ttk.Entry(params_labelframe, textvariable=max_price_var, width=20)
        max_price_entry.grid(row=1, column=1, sticky=tk.EW, pady=5, padx=5)

        # 页面稳定延迟
        ttk.Label(params_labelframe, text="页面稳定延迟(ms):").grid(row=2, column=0, sticky=tk.W, pady=5)
        delay_stable_var = tk.StringVar()
        page_delay_entry = ttk.Entry(params_labelframe, textvariable=delay_stable_var, width=20)
        page_delay_entry.grid(row=2, column=1, sticky=tk.EW, pady=5, padx=5)

        # 购买页等待延迟
        ttk.Label(params_labelframe, text="购买页等待延迟(ms):").grid(row=3, column=0, sticky=tk.W, pady=5)
        delay_buy_var = tk.StringVar()
        buy_delay_entry = ttk.Entry(params_labelframe, textvariable=delay_buy_var, width=20)
        buy_delay_entry.grid(row=3, column=1, sticky=tk.EW, pady=5, padx=5)
        
        # 耗时日志开关
        global enable_time_log
        self.enable_time_log_var = tk.BooleanVar(value=enable_time_log)
        time_log_check = ttk.Checkbutton(
            params_labelframe, 
            text="启用耗时日志", 
            variable=self.enable_time_log_var,
            command=self.toggle_time_log
        )
        time_log_check.grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=5, padx=5)
        
        params_labelframe.grid_columnconfigure(1, weight=1)

        # --- 右侧 --- 
        # 状态显示
        status_frame = ttk.Frame(right_frame)
        status_frame.pack(fill=tk.X, pady=(0,5))
        status_var = tk.StringVar(value="状态: 未运行")
        status_label = ttk.Label(status_frame, textvariable=status_var, font=("微软雅黑", 10))
        status_label.pack(side=tk.RIGHT)
        
        # 运行日志
        log_labelframe = ttk.LabelFrame(right_frame, text="运行日志", padding=10)
        log_labelframe.pack(fill=tk.BOTH, expand=True)

        log_text = scrolledtext.ScrolledText(log_labelframe, wrap=tk.WORD, height=10, width=40)
        log_text.pack(fill=tk.BOTH, expand=True)
        log_text.configure(state='disabled')

        # --- 底部框架 --- 
        bottom_frame = ttk.Frame(master, padding=(10,0,10,10))
        bottom_frame.pack(fill=tk.X)

        # 按钮框架
        button_frame = ttk.Frame(bottom_frame)
        button_frame.pack(fill=tk.X, pady=(5,5))

        ttk.Button(button_frame, text="开始运行", command=start_loop, width=12).pack(side=tk.LEFT, padx=(0,5))
        ttk.Button(button_frame, text="暂停/继续", command=pause_loop, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="停止运行", command=stop_loop, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="保存配置", command=save_config_from_ui, width=12).pack(side=tk.LEFT, padx=5)
        
        # 点击次数显示
        self.click_count_var = tk.StringVar(value="本次运行共点击购买按钮 0 次")
        click_count_label = ttk.Label(bottom_frame, textvariable=self.click_count_var)
        click_count_label.pack(fill=tk.X, pady=(5,0))
        global click_count_var
        click_count_var = self.click_count_var

        # 热键提示
        hotkey_label = ttk.Label(bottom_frame, text="F8:开始 F9:暂停/继续 F10:停止")
        hotkey_label.pack(fill=tk.X, pady=(5,5))

        # 版权信息
        copyright_label = ttk.Label(bottom_frame, text="© 2025 P1nKM41D 版权所有 | 软件版本:v1.0.1", font=("微软雅黑", 8))
        copyright_label.pack(fill=tk.X)

        # 启动日志更新
        update_log_display()
        
        # 初始化配置
        init_config()

    def on_mode_change(self, event=None):
        selected_mode = mode_var.get()
        log(f"模式切换到: {selected_mode}")
        # 模式切换时，重新初始化配置以加载新模式的价格
        init_config()
        
    def toggle_time_log(self):
        """切换耗时日志开关"""
        global enable_time_log
        enable_time_log = self.enable_time_log_var.get()
        status = "启用" if enable_time_log else "禁用"
        log(f"耗时日志已{status}")

# 主程序启动部分
if __name__ == "__main__":
    if not pyuac.isUserAdmin():
        log("以管理员权限重新启动...")
        pyuac.runAsAdmin()
    else:
        log("已拥有管理员权限")
        tk_root = tk.Tk()
        app = AppUI(tk_root)
        # 启动后台热键监听
        listener = keyboard.Listener(on_press=on_key_press)
        listener.start()
        tk_root.mainloop()