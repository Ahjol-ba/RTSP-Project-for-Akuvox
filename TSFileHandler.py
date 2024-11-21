import os
import av
import time
import queue
import threading
import numpy as np
import multiprocessing

class StreamWriter(threading.Thread):
    """用于将音视频帧编码并写入容器的线程"""
    def __init__(self, track_name, queue, stream, container, deserialize_func, rlock, stop_event):
        super().__init__()
        self.track_name = track_name  # 轨道名称，如'audio'或'video'
        self.queue = queue  # 存储音视频帧数据的队列
        self.stream = stream  # AV流对象，用于编码帧
        self.container = container  # 容器用于多路复用编码后的帧
        self.deserialize_func = deserialize_func  # 函数用于反序列化帧数据
        self.rlock = rlock  # 重入锁，用于同步写入容器
        self.stop_event = stop_event  # 停止事件，用于终止线程
        

    def run(self):
        """线程的执行函数，从队列中不断取出帧数据，编码后写入容器"""
        while not self.stop_event.is_set():
            try:
                data = self.queue.get_nowait()
                frame = self.deserialize_func(data)
                packet = self.stream.encode(frame)
                with self.rlock:
                    try:
                        self.container.mux(packet)
                    except Exception as e:
                        pass
                        # 发生异常时可以选择记录或处理
                        # print(f"Exception while muxing {self.track_name} frame: {e}")
                        # 一般报错为 [error 22]， 帧数据错误，可能是网络丢包造成的
            except queue.Empty:
                time.sleep(0.01) # 队列为空时暂停，避免CPU占用过高



class TSFileHandler(multiprocessing.Process):
    """多进程类，用于管理音视频流的读取、解码、编码和写入操作"""
    def __init__(self, \
                video_frame_que,\
                audio_frame_que,\
                stream_info_dict,\
                stop_event,\
                path = None,):
        super().__init__()
        self.frame_ques = {'video': video_frame_que, 'audio': audio_frame_que}  # 存储音视频帧的队列
        self.stream_info_dict = stream_info_dict  # 包含流信息的字典
        self.stop_event = stop_event # 停止事件
        script_dir = os.path.dirname(__file__)
        dir = os.path.join(script_dir, 'results')
        path = path or 'output_stream.ts'
        path = os.path.join(dir, path)
        self.path = path # 输出文件的路径
    

    def deserialize_audio_frame(self, data):
        """从二进制数据反序列化音频帧"""
        array = np.frombuffer(data["bytes_data"], dtype=np.dtype(data["dtype"])).reshape(data["shape"])
        frame = av.AudioFrame.from_ndarray(array, layout=data["layout"])
        frame.pts = data["pts"]
        frame.time_base = data["time_base"]
        # frame.samples = data["samples"]
        frame.sample_rate = data["sample_rate"]
        return frame

    def deserialize_video_frame(self, data):
        """从二进制数据反序列化视频帧"""
        array = np.frombuffer(data["bytes_data"], dtype=np.dtype(data["dtype"])).reshape(data["shape"])
        frame = av.VideoFrame.from_ndarray(array, format="yuv420p")
        frame.pts = data["pts"]
        # frame.width = data["width"]
        # frame.height = data["height"]
        frame.pict_type = data["pict_type"]
        frame.time_base = data["time_base"]
        return frame
    
    def run(self):
        """进程的主执行函数，初始化音视频流和编码器，启动编码线程"""
        container = av.open(self.path, mode='w',format='mpegts')    
        video_stream = None
        audio_stream = None
        rlock = threading.RLock()
        stream_writers = []

         # 等待流信息可用
        while self.stream_info_dict['status'] == None:
            time.sleep(0.01)

         # 根据流信息初始化视频和音频流
        if self.stream_info_dict['video']:
            video_stream = container.add_stream(codec_name='h264', rate=self.stream_info_dict["video_sample_rate"])
            video_stream.width = self.stream_info_dict["video_width"]
            video_stream.height = self.stream_info_dict["video_height"]
            video_stream.pix_fmt = 'yuv420p'
            video_stream.bit_rate = 3000000
            stream_writers.append(StreamWriter('video', self.frame_ques['video'], video_stream, container, self.deserialize_video_frame, rlock, self.stop_event))

        if self.stream_info_dict['audio']:    
            audio_stream = container.add_stream(codec_name='aac', rate=self.stream_info_dict.get("sample_rate"))
            stream_writers.append(StreamWriter('audio', self.frame_ques['audio'], audio_stream, container, self.deserialize_audio_frame, rlock, self.stop_event))
            


        for sw in stream_writers:
            sw.start()
    
        
        while not self.stop_event.is_set():
            time.sleep(1)
        
        # 等待所有编码线程结束
        for sw in stream_writers:
            sw.join()
            
        container.close() # 关闭容器，完成文件写入






