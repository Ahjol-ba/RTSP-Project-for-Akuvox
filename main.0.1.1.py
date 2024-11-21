
import time
import multiprocessing
from LoadConfig import CONFIG
from TSFileHandler import TSFileHandler
from RTSPStreamHandler import RTSPStreamHandler
from AnalyzeVideo import VideoAnalyProcesser


    
def main():
    # 从配置文件中提取服务器地址、端口和路径
    server_host = CONFIG.get('server_host')
    server_port = CONFIG.get('server_port')
    path = CONFIG.get('path') 
    # 多进程管理器
    manager = multiprocessing.Manager() 
    # 事件，用于跨进程通信，控制停止操作
    stop_event = manager.Event()

    # 共享字典，存储流信息（视频、音频状态和整体状态）
    stream_info_dict = manager.dict({
        'video': False,
        'audio': False,
        'status': None,
    }) 
    
    # 创建视频和音频队列
    v_que_for_ts = manager.Queue() # 用于从RTSPStreamHandler向TSFileHandler传递视频帧数据
    a_que_for_ts = manager.Queue() # 用于从RTSPStreamHandler向TSFileHandler传递音频帧数据
    v_que_for_av = manager.Queue() # 用于从RTSPStreamHandler向VideoAnalyProcesser传递视频帧数据

    video_frame_ques = [v_que_for_ts, v_que_for_av] # 用于传递视频帧的队列列表
    audio_frame_ques = [a_que_for_ts] # 用于传递音频帧的队列列表

    # 初始化RTSP流处理器，负责获取视频和音频流以及帧数据
    rtsp_stream_handler = RTSPStreamHandler(
                                        video_frame_ques,
                                        audio_frame_ques,
                                        stream_info_dict,
                                        stop_event, 
                                        f"rtsp://{server_host}:{server_port}/{path}")
    # 初始化TS文件处理器
    ts_file_handler = TSFileHandler(v_que_for_ts, a_que_for_ts, stream_info_dict, stop_event)
    # 初始化视频分析处理器
    video_analyzer = VideoAnalyProcesser(v_que_for_av, stream_info_dict, stop_event)

    video_analyzer.start()
    ts_file_handler.start()
    rtsp_stream_handler.start()

    # 主循环：等待停止事件被设置或监控流的状态变化
    while not stop_event.is_set():
        if stream_info_dict['status']:
            if stream_info_dict['status'] == 'start':
                # 当流开始时，等待用户输入以停止处理
                print("\r\nPress 'Enter' to stop.\r\n")
                input()
            if stream_info_dict['status'] == 'end':
                # 如果流结束，无需额外操作
                pass
            # 设置停止事件，结束所有处理
            stop_event.set()
            break
        time.sleep(0.1)
    
    # 确保所有事件和线程都被清理和同步
    rtsp_stream_handler.join()
    ts_file_handler.join()
    video_analyzer.join()


if __name__ == '__main__':
    main()





    