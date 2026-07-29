import ollama

response = ollama.chat(
    model='gemma4:e4b', 
    messages=[
      {
        'role': 'user',
        'content': 'フィジカルAIの実験をしようとしています。電子機器の回路図は読めますか?',
      },
    ],
    think=False
)
print(response['message']['content'])

