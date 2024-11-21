import time
import queue
import threading
import multiprocessing
import numpy as np
from Srt import Srt
from ping3 import ping
from RTP import RTP
from Srt import Srt


class SharedValue:
    """用于线程间共享数据, 包含一个可锁定的变量"""
    def __init__(self):
        self.value = 0
        self.lock = threading.Lock()


class Ping(threading.Thread):
    """通过ping命令检测网络延迟, 并更新共享变量"""
    def __init__(self, server_host:str, delay:SharedValue, stop_event, timeout = 0.45):
        super().__init__()
        self.delay = delay
        self.server_host = server_host
        self.stop_event = stop_event
        self.timeout = timeout
    
    def run(self):
        while not self.stop_event.is_set():
            try:
               delay = ping(self.server_host, self.timeout)
               with self.delay.lock:
                  self.delay.value = delay if delay is not None else 0  # 如果ping返回None, 则视为0延迟
            except Exception as e:
                  with self.delay.lock:
                     self.delay.value = None
                  print(f"Error during ping: {e}")


class NetAnalyzerForEachTrack(threading.Thread):
    """为每个视频/音频轨道处理接收的RTP包, 计算丢包、抖动等网络指标"""
    def __init__(self, init_data, input_que:queue.Queue, delay:SharedValue, stop_event):
        super().__init__()
        self.srt = Srt(f'{init_data['type']}-Net-Status', init_data['sample_rate'])
        self.input_que = input_que
        self.delay = delay
        self.stop_event = stop_event

        self.max_seq_num = 65535  # 序列号的最大值
        self.max_timestamp = 4294967296  # 时间戳的最大值
    
        self.track_id = init_data['track_id']
        self.type = init_data['type']
        self.ssrc = init_data['ssrc']
        self.sample_rate = init_data['sample_rate']
        self.init_seq = init_data['init_seq']
        self.init_timestamp = init_data['init_timestamp']

        
        self.prev_seq = self.init_seq - 1
        self.prev_timestamp = self.init_timestamp
        self.prev_arrival_time = time.perf_counter()

        self.jitter = []
        self.pts_carry = 0
        self.prev_pts = 0
        
        
        self.loss_num = 0
        self.total_loss_num = 0
        self.recv_num = 1
        self.total_recv_num = 1

        

    def get_delay(self):
        """安全获取当前延迟值"""
        with self.delay.lock:
            return self.delay.value
        
    def estimate_loss(self, prev_seq, curr_seq):
        """估计丢包数量, 处理环绕"""
        loss_pack = 0
        if curr_seq < prev_seq:
            if prev_seq > (self.max_seq_num - 35) and curr_seq < 35: # 绕回检测 (65500 < prev & curr < 35)
                loss_pack = (curr_seq + self.max_seq_num) - prev_seq - 1
            else:
                return None
        else:
            loss_pack = curr_seq - prev_seq - 1
        return loss_pack


    def calculate_pts(self, prev_timestamp, curr_timestamp):
        """计算时间戳跨度, 处理环绕"""
        if curr_timestamp < prev_timestamp:
            if prev_timestamp > (self.max_timestamp - self.sample_rate) and curr_timestamp < self.sample_rate: # 绕回检测 (4294967296 - sample_rate < prev & curr < sample_rate)
                self.pts_carry += 1
        return (curr_timestamp - self.init_timestamp) + (self.max_timestamp * self.pts_carry)
    
    def rtp_packet_handler(self, rtp:RTP) -> dict:
        """处理单个RTP包, 计算网络指标"""
        loss_num = self.estimate_loss(self.prev_seq, rtp.seq)

        
        if loss_num == None:
            return
        
        self.loss_num += loss_num
        self.recv_num += 1 + loss_num
        self.total_loss_num += loss_num
        self.total_recv_num += 1 + loss_num
                    
        self.jitter.append(rtp.arrival_time - self.prev_arrival_time)

        curr_pts = self.calculate_pts(self.prev_timestamp, rtp.timestamp)

        if curr_pts - self.prev_pts > self.sample_rate / 2:
            # 每半秒生成一次字幕帧数据        
            curr_delay = 0.99999
            
            with self.delay.lock:
                if self.delay.value:
                    curr_delay = self.delay.value * 1000
            
            jitter = np.mean(self.jitter) * 1000 
            
            loss_rate = self.loss_num / self.recv_num * 100
            
            total_loss_rate = self.total_loss_num / self.total_recv_num * 100
            
            report_text = f"Track:{self.type}, Delay: {curr_delay:.2f} ms, Jitter: {jitter:.2f} ms, Loss_rate: {loss_rate:.2f} %, Total_loss_rate: {total_loss_rate:.2f} %"
            self.srt.write_srt(report_text, curr_pts , curr_pts + self.sample_rate // 2)
            
            
            self.loss_num = 0
            self.recv_num = 0
            self.jitter.clear()
            self.prev_pts = curr_pts
            

        self.prev_seq = rtp.seq
        self.prev_timestamp = rtp.timestamp
        self.prev_arrival_time = rtp.arrival_time
    
    def run(self):
        """不断从输入队列获取RTP包并处理"""
        while not self.stop_event.is_set() or not self.input_que.empty():
            try:
                rtp_packet = self.input_que.get_nowait()
                self.rtp_packet_handler(rtp_packet)
                        
            except queue.Empty:
                time.sleep(0.01)
        

class NetAnalyProcesser(multiprocessing.Process):
    """网络分析处理器，负责管理网络分析任务"""
    def __init__(self, input_que:queue.Queue, server_host, pipeline, stop_event):
        super().__init__()
        
        self.server_host = server_host
        self.input_que = input_que
        
        self.pipeline = pipeline
        self.stop_event = stop_event
        self.tasks = []
        self.queues = {}
        
        


    def run(self):
        
        delay = SharedValue()
        self.tasks.append(Ping(self.server_host, delay, self.stop_event))

        while not self.stop_event.is_set():
            recv = self.pipeline.recv()
            if recv == 'start':
                break
            else:
                ssrc = recv["ssrc"]
                new_queue = queue.Queue()
                self.queues[ssrc] = new_queue
                self.tasks.append(NetAnalyzerForEachTrack(recv, new_queue, delay, self.stop_event))

        for task in self.tasks:
            task.start()
        

        while not self.stop_event.is_set() or not self.input_que.empty():
            try:
                data = self.input_que.get_nowait()
                rtp_packet = RTP(data)
                if rtp_packet.is_rtp_packet:
                    self.queues[rtp_packet.ssrc].put(rtp_packet)
            except queue.Empty:
                time.sleep(0.01)
        
        for task in self.tasks:
            task.join()
    





























    