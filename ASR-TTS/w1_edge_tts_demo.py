import asyncio
import edge_tts
import argparse

async def run_tts(text, output):
    try:
        ssml_text = f"<speak>{text}</speak>"
        tts = edge_tts.Communicate(ssml_text, 'zh-CN-XiaoxiaoNeural')
        await tts.save(output)
        print('✅ 语音生成成功：', output)
    except Exception as e:
        print("❌ 语音合成失败，文字内容：", text)
        print("错误信息：", e)

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--text', default="你好，这是默认语音", help="要转换的文字")
    p.add_argument('--output', default='output.mp3')
    args = p.parse_args()

    asyncio.run(run_tts(args.text, args.output))