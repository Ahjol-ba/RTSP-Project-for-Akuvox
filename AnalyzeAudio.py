
import av
import time
import queue
import webrtcvad
import threading
import numpy as np
import multiprocessing
from Srt import Srt 


class DataHandler(threading.Thread):
    """负责从队列中接收音频数据，进行反序列化，并传递给分析线程"""
    def __init__(self, input_que:multiprocessing.Queue, frame_que:queue.Queue, stop_event:threading.Event):
        super().__init__()
        self.input_que = input_que  # 输入队列
        self.frame_que = frame_que  # 帧队列
        self.stop_event = stop_event  # 停止事件

    def deserialize_audio_frame(self, data):
        """从二进制数据反序列化为音频帧"""
        array = np.frombuffer(data["bytes_data"], dtype=np.dtype(data["dtype"])).reshape(data["shape"])
        frame = av.AudioFrame.from_ndarray(array, layout=data["layout"])
        frame.planes[0]
        frame.pts = data["pts"]
        frame.time_base = data["time_base"]
        frame.sample_rate = data["sample_rate"]    
        return frame

    def run(self):
        """持续从输入队列中获取数据，反序列化并放入帧队列"""
        while not self.stop_event.is_set() or not self.input_que.empty():
            try:
                data = self.input_que.get_nowait()
                frame = self.deserialize_audio_frame(data)
                self.frame_que.put(frame)

            except queue.Empty:
                time.sleep(0.1)
        



class AudioAnalyzer(threading.Thread):
    """负责从帧队列中取出音频帧并进行声音活动分析"""
    def __init__(self, sample_rate:int, frame_que: queue.Queue,  stop_event):
        super().__init__()
        self.frame_que = frame_que
        self.stop_event = stop_event

        self.avg_noise = None
        self.max_noise = -float('inf')
        self.avg_voice = None
        self.max_voice = -float('inf')
        self.last_pts = 0

        self.srt = Srt(f"Audio-Status", sample_rate)
        self.vad = webrtcvad.Vad(1)  # 语音活动检测器
    
    def run(self):
        """不断处理帧队列中的音频帧，执行声音活动分析"""
        while not self.stop_event.is_set() or not self.frame_que.empty():
            try:
                frame = self.frame_que.get_nowait()
                self.process_frame(frame)

            except queue.Empty:
                time.sleep(0.1)

    def padding_length(self, frame_bytes, target_length):
        """调整帧字节长度至目标长度"""
        current_length = len(frame_bytes)
        if current_length > target_length:
            return frame_bytes[:target_length]
        elif current_length < target_length:
            padding_length = target_length - current_length
            return frame_bytes + (b'\x00' * padding_length)
        return frame_bytes

    def calculate_voice_to_noise_ratio(self):
        """计算声音与噪声的比率"""
        if self.avg_noise == 0 or self.avg_noise == None or self.avg_voice == None:
            return None
        else:
            return self.avg_voice / self.avg_noise
        
    def calculate_max_db(self, frame_bytes):
        """计算最大分贝值"""
        max_val = np.max(np.abs(frame_bytes))
        if max_val > 0:
            return 20 * np.log10(max_val)
        return 0
    

    

    def process_frame(self, frame:av.AudioFrame):
        """处理单个音频帧，评估声音活动并记录相关数据"""
        sample_rate = frame.sample_rate
        frame_int16 = frame.to_ndarray().astype('int16')
        max_db = self.calculate_max_db(frame_int16)
        frame_bytes = frame_int16.tobytes()
        frame_bytes = self.padding_length(frame_bytes, 320)
        is_speech = self.vad.is_speech(frame_bytes, sample_rate)
        
        if is_speech:
            self.max_voice = max(max_db, self.max_voice)
            if max_db != 0:
                if self.avg_voice == None:
                    self.avg_voice = max_db
                else:
                    self.avg_voice = np.mean([max_db, self.avg_voice])
        else:
            self.max_noise = max(max_db, self.max_noise)
            if max_db != 0:
                if self.avg_noise == None:
                    self.avg_noise = max_db
                else:
                    self.avg_noise = np.mean([max_db, self.avg_noise])

        if frame.pts - self.last_pts > 0.45 * frame.sample_rate:
            ratio = self.calculate_voice_to_noise_ratio()
            if ratio:
                self.srt.write_srt(f"Max Voice:{self.max_voice:.2f} db, Max Noise:{self.max_noise:.2f} db, Voice(mean) to Noise(mean) Ratio: {ratio:.2f}", self.last_pts, frame.pts)
            else:
                self.srt.write_srt(f"Max Voice:{self.max_voice:.2f} db, Max Noise:{self.max_noise:.2f} db, Voice(mean) to Noise(mean) Ratio: None", self.last_pts, frame.pts)
            self.max_noise = 0
            self.max_voice = 0
            self.last_pts = frame.pts



class AudioAnalyProcesser(multiprocessing.Process):
    """音频分析流程的多进程类，负责音频数据处理和分析线程的管理"""
    def __init__(self, input_que, stream_info_dict, stop_event):
        super().__init__()
        self.input_que = input_que
        self.stream_info_dict = stream_info_dict
        self.stop_event = stop_event
       

    def run(self):
        """进程运行函数，监控音频流状态并启动音频处理和分析线程"""
        while self.stream_info_dict['status'] == None:
            time.sleep(0.01)

        if self.stream_info_dict['audio']:
                
            frame_que = queue.Queue()
            data_handler = DataHandler(self.input_que, frame_que, self.stop_event)
            analyzer = AudioAnalyzer(self.stream_info_dict['audio_sample_rate'], frame_que, self.stop_event)

            analyzer.start()
            data_handler.start()
            while not self.stop_event.is_set():
                time.sleep(0.5)
            data_handler.join()
            analyzer.join()

