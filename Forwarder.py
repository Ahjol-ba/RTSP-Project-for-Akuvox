import re
import time
import socket
import threading
import multiprocessing


class TCPPacketForwarder(threading.Thread):
    """TCP包转发器, 基础类, 用于从源socket接收数据并转发到目标socket"""
    def __init__(self, src_sock:socket.socket, dst_sock:socket.socket, stop_event):
        threading.Thread.__init__(self)
        self.src_sock = src_sock  # 源socket
        self.dst_sock = dst_sock  # 目标socket
        self.buffer = b''  # 数据缓冲
        self.stop_event = stop_event  # 停止事件
  
    def data_handler(self, data):
        """数据处理方法, 基础实现仅将接收的数据放入缓冲区"""
        self.buffer = data
    
    def run(self):
        """不断从源socket接收数据并转发到目标socket, 直至收到停止信号"""
        self.src_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        while not self.stop_event.is_set():
            try:
                data = self.src_sock.recv(4096)
                self.data_handler(data)
                self.dst_sock.sendall(self.buffer)
                self.buffer = b''
            except socket.error:
                break
        self.cleanup()

    def cleanup(self):
        """清理方法, 关闭socket连接"""
        self.src_sock.close()
        self.dst_sock.close()
    
class ServerPacketHandler(TCPPacketForwarder):
    """服务器端包处理器, 扩展自TCP包转发器, 用于解析RTSP协议信息"""
    def __init__(self, 
                src_sock: socket.socket, 
                dst_sock: socket.socket, 
                stop_event, 
                rtp_queue:multiprocessing.Queue, 
                pipeline):
        super().__init__(src_sock, dst_sock, stop_event)
        self.init_info = [{}, {}]  # 初始化信息存储
        self.rtp_queue = rtp_queue  # RTP数据队列
        self.pipeline = pipeline  # 管道用于发送初始化信息
    
    def rtsp_packet_handler(self, packet:str):
        """RTSP数据包处理方法, 解析RTSP响应及其内容"""
        if packet.startswith("RTSP/1.0"):
            status_code = re.search(r"RTSP/1.0 ([0-9]+) (.*)\r\n", packet).group(1)
            if status_code != '200':
                self.stop_event.set()
                
            elif "Content-Type: application/sdp" in packet:
                sdp = packet.split("\r\n\r\n")[1]
                tracks = sdp.split("m=")[1:]
                for track in tracks:
                    track_type = re.search(r"([a-zA-Z]+) (.*)",track).group(1)
                    track_id = int(re.search(r"trackID=([0-9])\r\n",track).group(1))
                    sample_rate = int(re.search(r"a=rtpmap:([0-9]+) ([a-zA-Z0-9]+)/([0-9]+)\r\n", track).group(3))
                    self.init_info[track_id]["type"] = track_type
                    self.init_info[track_id]["track_id"] = track_id
                    self.init_info[track_id]["sample_rate"] = sample_rate
            
            elif "Transport" in packet:
                trans_info = re.search(r"Transport: (.*)\r\n", packet).group(1)
                track_id = int(re.search(r"interleaved=([0-9])-([0-9])",trans_info).group(1))//2
                ssrc = int(re.search(r"ssrc=([0-9a-zA-Z]+)",trans_info).group(1), 16)
                self.init_info[track_id]["ssrc"] = ssrc
                
            elif "RTP-Info" in packet:
                rtp_info = re.search(r"RTP-Info: (.*)\r\n", packet).group(1)
                tracks = rtp_info.split('url=')[1:]
                for track in tracks:
                    items = track.split(";")
                    track_id = int(re.search(r"trackID=([0-9])",items[0]).group(1))
                    seq = int(re.search(r"seq=([0-9]+)", items[1]).group(1))
                    rtptime = int(re.search(r"rtptime=([0-9]+)", items[2]).group(1))
                    self.init_info[track_id]["init_seq"] = seq
                    self.init_info[track_id]["init_timestamp"] = rtptime
                    self.pipeline.send(self.init_info[track_id])
                self.pipeline.send('start')          

    def data_handler(self, data:bytes):
        """数据处理方法, 根据数据类型进行不同的处理逻辑"""
        if len(data) < 4:
            self.buffer += data
            return 
        rtsp_interleaved_head = data[:4]
        if rtsp_interleaved_head[0] == 0x24: # 检查RTP数据标识
            channel = rtsp_interleaved_head[1]
            length = rtsp_interleaved_head[2] * 256 + rtsp_interleaved_head[3]
            if channel == 0x00 or channel == 0x02:
                self.rtp_queue.put(data[4:16])
                self.buffer += data[:(4+length)]
                self.data_handler(data[(4+length):])
                return
        try:
            decoded_data = data.decode('utf-8')
            self.rtsp_packet_handler(decoded_data)
        except Exception:
            pass
        self.buffer = data
        
class ClientPacketHandler(TCPPacketForwarder):
    """客户端包处理器, 继承自TCP包转发器"""
    def __init__(self, src_sock: socket.socket, dst_sock: socket.socket, stop_event: threading.Event):
        super().__init__(src_sock, dst_sock, stop_event)

class RTSPForwarder(multiprocessing.Process):
    """RTSP转发器进程, 负责通过中继转发器建立RTSP客户端和服务器之间的通信"""
    def __init__(self,
                rtp_queue:multiprocessing.Queue, 
                server_host:str, 
                server_port:int, 
                pipeline,
                stop_event):
        super().__init__()
        self.pipeline = pipeline
        self.server_addr = (server_host, server_port)
        self.rtp_queue = rtp_queue
        self.stop_event = stop_event
        self.serve_list = []
        
    
        
        
    def create_socket(self, max_retries = 5, delay = 3):
        """尝试创建监听socket, 最大尝试次数为max_retries"""
        retries = 0
        while retries < max_retries:
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.bind(('127.0.0.1', 12024))
                self.sock.listen(5)
                self.sock.settimeout(1)
                break
            except socket.error as e:
                retries += 1
                print(f"Error in creating socket: {e}\r\nRetrying in {delay} seconds.")
                time.sleep(delay)
        if retries == max_retries:
            print("Fail to create socket.")
            self.stop_event.set()
            return
             
    def run(self):
        """进程主函数, 接受客户端连接并启动前后转发器线程"""
        self.create_socket()
        while not self.stop_event.is_set():
            try:
                client_sock, client_addr = self.sock.accept()
                server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                server_sock.connect(self.server_addr)
                forwarder_c2s = ClientPacketHandler(client_sock, server_sock, self.stop_event)
                self.serve_list.append(forwarder_c2s)
                forwarder_c2s.start()
                

                forwarder_s2c = ServerPacketHandler(server_sock, client_sock, self.stop_event, self.rtp_queue, self.pipeline)
                self.serve_list.append(forwarder_s2c)
                forwarder_s2c.start()
                

            except socket.timeout:
                continue

            except socket.error as e:
                # print(f"Error in RTSPForwarder:{e}")
                time.sleep(0.1)
                continue
        self.sock.close()
        for serve in self.serve_list:
            serve:TCPPacketForwarder
            serve.join()
        




