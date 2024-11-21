
import av
import os
import time
import queue
import threading
import numpy as np
import multiprocessing
from Srt import Srt
from vosk import Model, KaldiRecognizer
import json 

class DataHandler(threading.Thread):
    """处理音频数据的线程, 负责从进程队列中取出音频帧数据, 反序列化, 并放入线程队列中"""
    def __init__(self, input_que:multiprocessing.Queue, frame_que:queue.Queue, stop_event:threading.Event):
        super().__init__()
        self.input_que = input_que  # 进程间通信的队列
        self.frame_que = frame_que  # 线程间通信的队列
        self.stop_event = stop_event  # 停止事件

    def deserialize_audio_frame(self, data):
        """从二进制数据反序列化音频帧"""
        array = np.frombuffer(data["bytes_data"], dtype=np.dtype(data["dtype"])).reshape(data["shape"])
        frame = av.AudioFrame.from_ndarray(array, layout=data["layout"])
        frame.planes[0]
        frame.pts = data["pts"]
        frame.time_base = data["time_base"]
        frame.sample_rate = data["sample_rate"]    
        return frame

    def run(self):
        """线程主函数, 不断地处理音频帧直到接收到停止事件"""
        while not self.stop_event.is_set() or not self.input_que.empty():
            try:
                data = self.input_que.get_nowait()
                self.frame_que.put(self.deserialize_audio_frame(data))

            except queue.Empty:
                time.sleep(0.1)
        



class SpeechRecognizer(threading.Thread):
    """音频识别线程, 从队列中取出音频帧进行语音识别, 并将识别结果写入SRT文件"""
    def __init__(self, sample_rate, frame_que: queue.Queue, stop_event):
        super().__init__()
        self.sample_rate = sample_rate  # 音频采样率
        self.frame_que = frame_que  # 音频帧队列
        self.stop_event = stop_event  # 停止事件
        self.last_pts = 0  # 上一个音频帧的时间戳
        self.srt = Srt("Speech-Text", sample_rate)  # 初始化SRT文件处理类

    def init_recognizer(self, sample_rate):
        """初始化Vosk语音识别器"""
        script_dir = os.path.dirname(__file__)
        model_path = os.path.join(script_dir, 'Vosk-model-small-cn-0.22') # Vosk模型路径
        model = Model(model_path)
        return KaldiRecognizer(model, sample_rate)
    
    def recognize_speech(self, frame_bytes):
        """处理音频数据, 进行语音识别"""
        if self.recognizer.AcceptWaveform(frame_bytes):
            result = self.recognizer.Result()
            return f"{json.loads(result)['text']}"
    
    def process_frame(self, frame:av.AudioFrame):
        """处理单个音频帧, 从中识别语音并更新SRT文件"""
        frame_bytes = frame.to_ndarray().astype('int16').tobytes()
        result = self.recognize_speech(frame_bytes)
        if result:
            self.srt.write_srt(result, self.last_pts, frame.pts)
            self.last_pts = frame.pts

    def run(self):
        """线程主函数, 处理队列中的音频帧直到接收到停止事件"""
        self.recognizer = self.init_recognizer(self.sample_rate)
        while not self.stop_event.is_set() or not self.frame_que.empty():
            try:
                frame = self.frame_que.get_nowait()
                self.process_frame(frame)

            except queue.Empty:
                time.sleep(0.1)


class SpeechRecognizeProcesser(multiprocessing.Process):
    """负责语音识别的多进程类"""
    def __init__(self, input_que, stream_info_dict, stop_event,):
        super().__init__()
        self.input_que = input_que
        self.stream_info_dict = stream_info_dict
        self.stop_event = stop_event
       

    def run(self):
        """进程主函数, 初始化并启动音频处理和语音识别线程"""
        while self.stream_info_dict['status'] == None:
            time.sleep(0.01)

        if self.stream_info_dict['audio']:
            frame_que = queue.Queue()
            data_handler = DataHandler(self.input_que, frame_que, self.stop_event)
            speech_recoginzer = SpeechRecognizer(self.stream_info_dict['audio_sample_rate'], frame_que, self.stop_event)

            speech_recoginzer.start()
            data_handler.start()
            while not self.stop_event.is_set():
                time.sleep(0.5)
            data_handler.join()
            speech_recoginzer.join()
