# Yet another AI chat

A hybrid of AI assistant and AI roleplay, powered by locally running LLMs.

It probably doesn't have much practical sense since there are more powerful services, but I like the result and want to share it.

### Features

1. Role play. Chat with an AI that pretends to be a human. There are several personality templates.
2. To answer questions AI can use web search via DuckDuckGo API and it is reasonably integrated with the role play.
3. Memory system based on similarity of embeddings.
4. LLMs run locally. No external services (except of DuckDuckGo search) are used.

### Dependencies

- Python3
- ChromaDB (`pip3 install chromadb`)
- Flask (`pip3 install flask`)
- [llama.cpp](https://github.com/ggerganov/llama.cpp)

### Models

Two instances of llama.cpp server are used at the same time.

Tested with the following models:
- https://huggingface.co/TheBloke/MythoMax-L2-13B-GGUF/blob/main/mythomax-l2-13b.Q4_K_M.gguf (13B, context 4096 tokens) - used to generate chat messages;
- https://huggingface.co/TheBloke/openchat_3.5-GGUF/blob/main/openchat_3.5.Q4_K_M.gguf (7B, context 8192 tokens) - used for question classification, for logic tasks, and for web pages summarization;

If both models run on GPU requires about 20 GB of video memory. Llama.cpp can work on CPU as well, but it is quite slow.
