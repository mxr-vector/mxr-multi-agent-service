import bs4
import requests
from langchain_core.documents import Document

# Below is a minimal helper for demonstration purposes.
def __load_web_page(url: str, bs_kwargs: dict | None = None) -> list[Document]:
    '''
    Load a web page and return a list of documents.
    '''
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    soup = bs4.BeautifulSoup(response.text, "html.parser", **(bs_kwargs or {}))
    return [Document(page_content=soup.get_text(), metadata={"source": url})]


def preprocess_web_docs(urls: list[str]) -> list[Document]:
    '''
    Preprocess web documents from a list of URLs.
    '''
    return [__load_web_page(url) for url in urls]
    

def doc_splits(docs: list[Document]) -> list[Document]:
    '''
    Split documents into smaller chunks.
    '''
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    docs_list = [item for sublist in docs for item in sublist]

    text_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        chunk_size=100,
        chunk_overlap=50,
    )
    return text_splitter.split_documents(docs_list)



if __name__ == "__main__":
    urls = [
        "https://lilianweng.github.io/posts/2024-11-28-reward-hacking/",
        "https://lilianweng.github.io/posts/2024-07-07-hallucination/",
        "https://lilianweng.github.io/posts/2024-04-12-diffusion-video/",
    ]
    docs = preprocess_web_docs(urls)
    split_docs = doc_splits(docs)
    print(split_docs)
