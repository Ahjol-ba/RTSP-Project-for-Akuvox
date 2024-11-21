import time
import struct

class RTP:
    """处理RTP数据包的类, 可以解析字节序列和字典格式的数据包, 并将解析的数据序列化为字典"""
    def __init__(self, packet):
        self.is_rtp_packet = False  # 标记是否成功解析了一个有效的RTP数据包
        self.payload_type = None  # 载荷类型（音频/视频）
        self.seq = None  # RTP数据包的序列号
        self.timestamp = None  # RTP头部的时间戳
        self.ssrc = None  # 同步源标识符, 每个源唯一
        self.arrival_time = None  # 数据包处理的到达时间
    
        # 根据输入的数据包类型进行解析
        if isinstance(packet, dict):
            self.from_dict(packet)
        else:
            self.from_bytes(packet)

    def from_dict(self, packet):
        """从字典格式初始化RTP对象"""
        self.payload_type = int(packet["payload_type"])
        self.seq = int(packet["seq"])
        self.timestamp = int(packet["timestamp"])
        self.ssrc = int(packet["ssrc"])
        self.arrival_time = float(packet["arrival_time"])

    def from_bytes(self, packet):
        """从字节序列初始化RTP对象"""
        RTP_HEADER_LENGTH = 12  # RTP头部固定长度
        if len(packet) < RTP_HEADER_LENGTH:
            return  # 如果数据包太短, 则返回而不设置is_rtp_packet
        
        version = (packet[0] >> 6) & 0x03  # 提取RTP版本
        self.payload_type = packet[1] & 0x7F  # 提取载荷类型
        
        # 验证RTP版本和载荷类型是否为已知支持的类型
        if version != 2 or self.payload_type not in [0, 8, 96, 97, 98]:
            return None

        self.is_rtp_packet = True # 标记这是一个有效的RTP数据包
        rtp_header = struct.unpack('!BBHII', packet[:12])
        self.seq = rtp_header[2]
        self.timestamp = rtp_header[3]
        self.ssrc = rtp_header[4]
        self.arrival_time = time.perf_counter() # 记录当前时间为到达时间


    def to_dict(self):
        """将RTP数据包数据序列化为字典格式"""
        return {
            "payload_type": self.payload_type,
            "seq": self.seq,
            "timestamp": self.timestamp,
            "ssrc": self.ssrc,
            "arrival_time": self.arrival_time
        }