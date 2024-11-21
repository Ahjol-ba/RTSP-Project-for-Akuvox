import os
class Srt():
    def __init__(self, filename, sample_rate):
        """
        初始化Srt类, 设置字幕文件路径, 并准备写入
        Args:
            filename (str): 字幕文件的基础名称
            sample_rate (int): 用于时间计算的样本率
        """
        # 获取脚本文件所在目录
        script_dir = os.path.dirname(__file__)
        # 创建存放结果的目录，如果不存在则创建
        dir = os.path.join(script_dir, 'results')
        if not os.path.exists(dir):
             os.mkdir(dir)
        # 构造字幕文件的完整路径
        path = os.path.join(dir, f"{filename}.srt")
        # 打开字幕文件准备写入，如果文件不存在会自动创建
        open(path, 'w', encoding='utf-8')
        
        # 存储文件路径、初始化字幕序号和样本率
        self.path = path
        self.index = 1
        self.sample_rate = sample_rate

    def pts_to_srt_time(self, pts):
        """将PTS时间(基于样本率的时间戳)转换为SRT字幕文件中的时间格式
        Args:
            pts (int): 时间戳(Presentation Time Stamp)
        Returns:
            str: 转换后的时间字符串，格式为 '小时:分钟:秒,毫秒'
        """
        play_time = pts / self.sample_rate
        hours = int(play_time // 3600)
        minutes = int((play_time % 3600) // 60)
        seconds = int(play_time % 60)
        milliseconds = int((play_time - int(play_time)) * 1000)    
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


    def write_srt(self, text, start, end):
        """将一条字幕写入文件
        Args:
            text (str): 字幕文本
            start (int): 字幕开始时间(pts)
            end (int): 字幕结束时间(pts)
        """
        with open(self.path, 'a', encoding='utf-8') as file:
            file.write(f"{self.index}\n")
            file.write(f"{self.pts_to_srt_time(start)} --> {self.pts_to_srt_time(end)}\n")
            file.write(f"{text}\n\n")
            self.index += 1

