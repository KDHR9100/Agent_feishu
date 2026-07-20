import lark_oapi as lark
import logging
import time
import sys

def do_p2_im_message_receive_v1(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    print("[Feishu WS] Received message event: type=im.message.receive_v1")
    try:
        event_data = lark.JSON.marshal(data, indent=4)
        print("[Feishu WS] Message data: %s" % event_data)
    except Exception as e:
        print("[Feishu WS] Failed to process message: %s" % str(e))

def do_message_event(data: lark.CustomizedEvent) -> None:
    print("[Feishu WS] Received customized event")
    try:
        event_data = lark.JSON.marshal(data, indent=4)
        print("[Feishu WS] Customized event data: %s" % event_data)
    except Exception as e:
        print("[Feishu WS] Failed to process customized event: %s" % str(e))

def start_feishu_ws(app_id, app_secret):
    if not app_id or not app_secret:
        print("[Feishu WS] Feishu credentials not configured")
        return
    
    try:
        event_handler = lark.EventDispatcherHandler.builder("", "") \
            .register_p2_im_message_receive_v1(do_p2_im_message_receive_v1) \
            .build()
        
        print("[Feishu WS] Initializing Feishu WS client with App ID: %s" % app_id)
        
        cli = lark.ws.Client(
            app_id, 
            app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.DEBUG
        )
        
        print("[Feishu WS] Starting Feishu WS client...")
        cli.start()
        
    except Exception as e:
        print("[Feishu WS] Failed to start Feishu WS client: %s" % str(e))

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        app_id = sys.argv[1]
        app_secret = sys.argv[2]
        start_feishu_ws(app_id, app_secret)
    else:
        print("[Feishu WS] Missing app_id or app_secret arguments")
