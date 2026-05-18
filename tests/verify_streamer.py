import zmq
import zmq.asyncio
import asyncio
import json

async def run_subscriber():
    context = zmq.asyncio.Context()
    socket = context.socket(zmq.SUB)
    socket.connect("ipc:///tmp/data_streamer.ipc")
    socket.subscribe("") # Subscribe to all topics

    print("ZMQ Subscriber started. Waiting for trade data...")
    try:
        while True:
            topic, data = await socket.recv_multipart()
            print(f"[{topic.decode('utf-8')}] {data.decode('utf-8')}")
    except KeyboardInterrupt:
        print("Stopping subscriber...")
    finally:
        socket.close()
        context.term()

if __name__ == "__main__":
    asyncio.run(run_subscriber())
