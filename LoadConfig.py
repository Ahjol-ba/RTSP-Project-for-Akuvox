import re
import os
import json

try:
    # 获取当前脚本文件所在的目录路径
    script_dir = os.path.dirname(__file__)
    # 构建配置文件的完整路径
    path = os.path.join(script_dir, "config.json")
    # 打开配置文件并加载为JSON格式
    with open(path,'r') as file:
        CONFIG = json.load(file)
        # 使用正则表达式匹配配置文件中的RTSP URL，并解析出服务器地址、端口和路径
        matched = re.match(r"rtsp://(\d+\.\d+\.\d+\.\d+):(\d+)/(.*)?", CONFIG.get("rtsp_url"))
        CONFIG["server_host"] = matched.group(1)  # 服务器IP地址
        CONFIG["server_port"] = int(matched.group(2))  # 服务器端口，转换为整数
        CONFIG["path"] = matched.group(3)  # RTSP路径 

except OSError:
    # 如果打开文件过程中遇到OS错误，抛出异常
    raise OSError("Error opening config.json file.")

except json.JSONDecodeError:
    # 如果解析JSON时遇到错误，抛出异常
    raise json.JSONDecodeError("Error decoding JSON from config.json file.")
    


# 主程序入口
if __name__ == "__main__":
    # 打印配置信息，确认加载是否正确
    print(CONFIG)