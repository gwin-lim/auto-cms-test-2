from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from openai import AsyncOpenAI
import httpx
import os
from dotenv import load_dotenv
import aiohttp
import json
import re

load_dotenv()
CMS_URL = os.getenv("CMS_URL", "http://cms:1337")
CMS_POST_KEY = os.getenv("CMS_POST_KEY_1")

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

http_client = httpx.AsyncClient()
client = AsyncOpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    http_client=http_client
)

def slugify(text: str) -> str:
    # 영어, 숫자, 한글만 허용하고 나머지는 '-'로 변경
    # \w는 영문자와 숫자를 포함
    # \uAC00-\uD7A3는 한글 문자 범위
    pattern = r'[^\w\uAC00-\uD7A3]+'
    slug = re.sub(pattern, '-', text)
    # 연속된 '-' 제거
    slug = re.sub(r'-+', '-', slug)
    # 시작과 끝의 '-' 제거
    return slug.strip('-').lower()

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "cms_url": CMS_URL})

@app.post("/generate")
async def generate_post(keyword: str = Form(...)):
    try:
        # 블로그 포스트 생성
        post_response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "당신은 전문적인 작가입니다. 주어진 키워드로 한국어 블로그 포스트를 작성해주세요. 결과물은 markdown 형식이어야 합니다. 전체 포스트의 제목이 있어야 합니다. 내용은 독자의 호기심을 불러 일으키는 개요로 시작 되며 최소 3개의 하위 주제에 대한 상세 문단을 작성해 주세요. 각 상세 문단 또한 개별적인 제목이 있어야 합니다. 또한 주장이나 의견이 포함 될 수 있으며, 이 경우 사실을 근거로 제시해야 합니다. 마지막으로 전체 내용을 요약 정리하는 문단으로 마무리 해야 합니다."
                },
                {
                    "role": "user",
                    "content": f"다음 키워드로 블로그 포스트를 작성해주세요: {keyword}"
                }
            ],
            temperature=0.7,
            max_tokens=1000
        )
        
        post_content = post_response.choices[0].message.content.strip()
        
        # 첫 번째 # 으로 시작하는 라인을 찾아 제목으로 사용
        title = ""
        for line in post_content.split('\n'):
            if line.startswith('# '):
                title = line.replace('# ', '').strip()
                break

        # 이미지 생성을 위한 프롬프트 작성
        image_prompt_response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "당신은 DALL-E 3를 위한 이미지 프롬프트 전문가입니다. 주어진 블로그 포스트 내용을 바탕으로 적절한 대표 이미지 생성 프롬프트를 작성해주세요. 프롬프트는 영어로 작성하고, 그라데이션을 거의 사용하지 않는 아름답고 간결한 minimalizm 일러스트를 만듭니다."
                },
                {
                    "role": "user",
                    "content": f"다음 블로그 포스트 내용에 어울리는 이미지 생성 프롬프트를 작성해주세요: {post_content[:500]}..."
                }
            ],
            temperature=0.7,
            max_tokens=200
        )

        image_prompt = image_prompt_response.choices[0].message.content

        # DALL-E 3로 이미지 생성
        image_response = await client.images.generate(
            model="dall-e-3",
            prompt=image_prompt,
            size="1024x1024",
            quality="standard",
            n=1,
        )

        # Create new entry in Strapi CMS
        cms_headers = {
            "Authorization": f"Bearer {CMS_POST_KEY}",
        }
        
        # Download image from URL
        image_url = image_response.data[0].url
        async with httpx.AsyncClient() as image_client:
            image_response = await image_client.get(image_url)
            image_data = image_response.content


        image_id = None
        # Upload image to Strapi Media Library
        async with httpx.AsyncClient() as media_client:
            files = {'files': (
                f"{slugify(title)}_main_image.png",
                image_data,
                'image/png'
            )}
            
            response = await media_client.post(
                f"{CMS_URL}/api/upload",
                headers=cms_headers,
                files=files
            )
            if response.status_code >= 300:
                raise Exception(f"이미지 업로드 오류: {response.text}")
                
            res_json = response.json()
            image_id = res_json[0]['id']
        

        async with httpx.AsyncClient() as document_client:
            response = await document_client.post(
                f"{CMS_URL}/api/blog-post-test-format-1s?status=draft",
                headers=cms_headers,
                json={
                    "data": {
                        "Title": title,
                        "Slug": slugify(title),
                        "PostText": post_content,
                        "MainImage": {
                            "id": image_id
                        }
                    }
                }
            )
            if response.status_code >= 300:
                raise Exception(f"블로그 포스트 생성 오류: {response.text}")

        return {
            "data": {
                "content": post_content,
                "image_prompt": image_prompt,
                "image_url": image_url,
            }
        }
    except Exception as e:
        return {"error": str(e)}
