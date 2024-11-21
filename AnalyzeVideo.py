
import av
import cv2
import time
import queue
import threading
import numpy as np
import multiprocessing
from Srt import Srt

class DataHandler(threading.Thread):
    """负责从队列中接收视频数据, 进行反序列化, 并缓存处理"""
    def __init__(self, input_que:multiprocessing.Queue, buffer_que:queue.Queue, stop_event):
        super().__init__()
        self.input_que = input_que  # 输入队列
        self.buffer_que = buffer_que  # 缓冲队列
        self.buffer = []  # 用于存储反序列化后的帧
        self.last_time = 0.0  # 上一帧的时间戳
        self.stop_event = stop_event  # 停止事件

    def deserialize_video_frame(self, data):
        """从二进制数据反序列化为视频帧"""
        array = np.frombuffer(data["bytes_data"], dtype=np.dtype(data["dtype"])).reshape(data["shape"])
        frame = av.VideoFrame.from_ndarray(array, format="yuv420p")
        frame.pts = data["pts"]
        frame.pict_type = data["pict_type"]
        frame.time_base = data["time_base"]
        return frame
 

    def run(self):
        """线程主函数, 不断处理输入数据, 反序列化, 存储到缓冲区"""
        while not self.stop_event.is_set() or not self.input_que.empty():
            try:
                data = self.input_que.get_nowait()
                frame = self.deserialize_video_frame(data)
                self.buffer.append(frame)
                if frame.time - self.last_time > 0.45:
                    if len(self.buffer) > 1:
                        if self.buffer_que:
                            self.buffer_que.put(self.buffer.copy())    
                        self.buffer.clear()
                    self.last_time = frame.time

            except queue.Empty:
                time.sleep(0.01)
        self.buffer_que.put(self.buffer.copy())
        

class VideoAnalyzer(threading.Thread):
    """视频数据的分析, 包括绿色比例、马赛克比例和比特率的计算"""
    def __init__(self, sample_rate:int, buffer_que:queue.Queue, stop_event):
        super().__init__()
        self.buffer_que = buffer_que
        self.srt = Srt(f"Video-Status", sample_rate)
        self.stop_event = stop_event
    
    def estimate_mosaic_ratio(self, frame:av.VideoFrame):
        """计算马赛克比例"""
        block_size = (128, 128)  # 块大小
        variance_threshold = 400  # 方差阈值
        image = frame.to_ndarray(format='bgr24')
        gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray_image, (3, 3), 0)
        height, width = blurred.shape
        mosaic_block_count = 0
        total_block_count = 0
        for y in range(0, height, block_size[1]):
            for x in range(0, width, block_size[0]):
                y_end = min(y + block_size[1], height)
                x_end = min(x + block_size[0], width)
                block = blurred[y:y_end, x:x_end]
                variance = np.var(block)
                if variance < variance_threshold:
                    mosaic_block_count += 1
                total_block_count += 1
        mosaic_ratio = mosaic_block_count / total_block_count
        return mosaic_ratio
        
    
    def estimate_green_ratio(self, frame):
        """计算绿色比例"""
        img = frame.to_ndarray(format='bgr24')
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        lower_green = np.array([35, 30, 20])
        upper_green = np.array([85, 255, 255])
        mask = cv2.inRange(hsv, lower_green, upper_green)
        green_ratio = np.sum(mask == 255) / (mask.shape[0] * mask.shape[1])
        return green_ratio  
    
    def estimate_bit(self, frame):
        """估算视频帧的位数据量"""
        y_bytes = frame.width * frame.height
        uv_bytes = (frame.width // 2) * (frame.height // 2) * 2  
        return (y_bytes + uv_bytes) / 8

    def estimate_rate(self, prev_frame, curr_frame):
        """估算视频帧率"""
        if prev_frame == None:
            return None
        pts_interval = curr_frame.pts - prev_frame.pts
        
        frame_rate = 1 / curr_frame.time_base / pts_interval
        return frame_rate
        
    def analyze_frames(self, buffer):
        """分析缓存的帧序列, 计算各项指标并写入SRT文件"""
        if len(buffer) < 2: return
        duration = buffer[-1].time  -  buffer[0].time
        
        frame_rates = []
        green_ratios = []
        mosaic_ratios = []
        total_bits = 0
        prev_frame = None
        
        for frame in buffer:
            mosaic_ratios.append(self.estimate_mosaic_ratio(frame))
            green_ratios.append(self.estimate_green_ratio(frame))
            total_bits += self.estimate_bit(frame)
            frame_rate = self.estimate_rate(prev_frame, frame)
            if frame_rate: frame_rates.append(frame_rate)
            prev_frame = frame
        
        bitrate_bps = total_bits / duration
        bitrate_mbps = bitrate_bps / 1e6
        green_ratio = np.mean(green_ratios)
        mosaic_ratio = np.mean(mosaic_ratios)
        frame_rate = np.mean(frame_rates)

        report_text = f"Resolution:({frame.width}, {frame.height}), Bitrate: {bitrate_mbps:.2f} mbps, Frame Rate: {frame_rate:.2f} fps, Mosaic Ratio: {mosaic_ratio * 100:.2f} %, Green Ratio: {green_ratio * 100:.2f} %"
        self.srt.write_srt(report_text, buffer[0].pts, buffer[-1].pts)
        
        
    def run(self):
        while not self.stop_event.is_set() or not self.buffer_que.empty():
            try:
                buffer = self.buffer_que.get_nowait()
                self.analyze_frames(buffer)
            except queue.Empty:
                time.sleep(0.01)


class VideoAnalyProcesser(multiprocessing.Process):
    """处理视频分析流程的多进程类"""
    def __init__(self, input_que, stream_info_dict, stop_event):
        super().__init__()
        self.input_que = input_que
        self.stream_info_dict = stream_info_dict
        self.stop_event = stop_event
       

    def run(self):
        """进程运行函数, 监控视频流状态并启动分析线程"""
        while self.stream_info_dict['status'] == None:
            time.sleep(0.01)

        if self.stream_info_dict['video']:
            buffer_que = queue.Queue()
            data_handler = DataHandler(self.input_que, buffer_que, self.stop_event)
            analyzer = VideoAnalyzer(self.stream_info_dict['video_sample_rate'], buffer_que, self.stop_event)

            analyzer.start()
            data_handler.start()
            while not self.stop_event.is_set():
                time.sleep(0.5)
            data_handler.join()
            analyzer.join()





