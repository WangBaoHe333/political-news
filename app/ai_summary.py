import openai

openai.api_key = "your-api-key"  # 请替换成你自己的API密钥

def generate_summary(text):
    response = openai.Completion.create(
        model="gpt-4",  # 你也可以使用gpt-3.5
        prompt=f"Summarize the following political news into 3 concise sentences:\n\n{text}",
        max_tokens=150
    )
    return response.choices[0].text.strip()