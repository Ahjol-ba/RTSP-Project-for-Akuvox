
import av
import time
import multiprocessing


class RTSPStreamHandler(multiprocessing.Process):
    """处理RTSP流, 从给定的URL读取音视频数据, 并将其序列化后放入对应的队列中"""
    def __init__(self,
                 video_frame_ques,
                 audio_frame_ques,
                 stream_info_dict,
                 stop_event,
                 rtsp_url:str = None,
                 options:str = None,
                 ):
        
        super().__init__()
        self.video_frame_ques = video_frame_ques  # 视频帧队列列表
        self.audio_frame_ques = audio_frame_ques  # 音频帧队列列表
        self.stream_info_dict = stream_info_dict  # 存储流信息的字典
        self.stop_event = stop_event  # 控制停止的事件
        self.rtsp_url = rtsp_url or "rtsp://127.0.0.1:12024/stream"  # RTSP流的URL
        self.options = options or {"rtsp_transport": "tcp", "stimeout": "10000000", "max_delay": "5000000"}  # RTSP流的连接选项
    
    def open_container(self, max_retries = 5, retry_delay = 3):
        """尝试打开RTSP流, 如果失败则重试, 直到达到最大重试次数或接收到停止事件"""
        retries = 0
        while retries < max_retries:
            if self.stop_event.is_set():
                return
            try:
                container = av.open(self.rtsp_url, options=self.options)
                return container
            except av.AVError as e:
                retries += 1
                print(f"Attempt {retries} failed: {e}")
                if retries < max_retries:
                    print(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    print("Could not open the URL.")
                    return None

    def serialize_video_frame(self, frame:av.VideoFrame):
        """将视频帧序列化为二进制数据"""
        array = frame.to_ndarray(format="yuv420p")
        return  {
                "bytes_data": array.tobytes(),
                "shape": array.shape,
                "dtype": array.dtype,
                "pts":frame.pts,
                "time_base":frame.time_base,
                "pict_type":frame.pict_type,
            }
    
    def serialize_audio_frame(self, frame:av.AudioFrame):
        """将音频帧序列化为二进制数据"""
        array = frame.to_ndarray()
        return  {
                "bytes_data": array.tobytes(),
                "shape": array.shape,
                "dtype": array.dtype,
                "pts": frame.pts,
                "time_base": frame.time_base,
                "layout": frame.layout.name,
                "sample_rate": frame.sample_rate,
        }
    

    def run(self):
        """进程的主执行函数, 负责管理RTSP流的接收和处理流程"""
        container = self.open_container()
        if container is not None:
            video_stream = None
            audio_stream = None
            
            for stream in container.streams:
                if stream.type == "video":
                    video_stream = stream
                if stream.type == "audio":
                    audio_stream = stream
                
            self.stream_info_dict.update({
                    "status": "start",
                    "video": video_stream is not None,
                    "audio": audio_stream is not None,
                    "video_sample_rate": int(1 / video_stream.time_base) if video_stream else None,
                    "audio_sample_rate": int(1 / audio_stream.time_base) if audio_stream else None,
                    "video_width": video_stream.width if video_stream else None,
                    "video_height": video_stream.height if video_stream else None,
                })
            
            while not self.stop_event.is_set():
                try:
                    for packet in container.demux(video_stream, audio_stream):
                        if self.stop_event.is_set():
                            break
                        for frame in packet.decode():
                            if isinstance(frame, av.VideoFrame):
                                serialized_video_frame = self.serialize_video_frame(frame)
                                for video_que in self.video_frame_ques:
                                    if not video_que.full():
                                        video_que.put(serialized_video_frame)
                                continue
                            if isinstance(frame, av.AudioFrame):
                                serialized_audio_frame = self.serialize_audio_frame(frame)
                                for audio_que in self.audio_frame_ques:
                                    if not audio_que.full():
                                        audio_que.put(serialized_audio_frame)
                                continue
                except Exception as e:
                    print(f"There is an Exception in RTSPStreamHandler:{e}\r\n")
                    break
            container.close()
        self.stop_event.set()
        time.sleep(0.1)
        self.stream_info_dict.update({"status":'end'})
        
            

        




