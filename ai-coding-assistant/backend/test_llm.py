import asyncio
import httpx

async def main():
    url = "http://host.docker.internal:11434/api/generate"
    payload = {
        "model": "qwen2.5-coder:7b",
        "prompt": "Hello",
        "stream": False
    }
    print(f"Connecting to {url}...")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            print("Status:", resp.status_code)
            print("Response:", resp.text[:200])
    except Exception as e:
        print("Error:", repr(e))

if __name__ == "__main__":
    asyncio.run(main())
