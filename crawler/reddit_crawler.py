import json
import logging
import os

import requests
from dotenv import load_dotenv


PROJECT_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
logger = logging.getLogger(__name__)


def load_reddit_config():
    """
    加载 Reddit 接口配置和本地认证信息，环境变量优先。

    :return: 接口配置字典
    """
    load_dotenv(os.path.join(PROJECT_PATH, ".env"), override=False)
    with open(os.path.join(PROJECT_PATH, "config", "reddit_config.json"), encoding="utf-8") as config_file:
        config = json.load(config_file)
    for variable_name in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USER_AGENT"):
        config[variable_name] = os.getenv(variable_name, "").strip()
        if not config[variable_name]:
            raise ValueError(f"缺少配置 {variable_name}，请在本地 .env 中填写获批应用的信息")
    return config


def check_reddit_response(response, stage):
    """
    检查接口状态，提供诊断信息且不记录响应正文或令牌。

    :param response: HTTP 响应
    :param stage: 请求阶段
    :return: 无
    """
    if response.status_code in (401, 403, 429):
        reason = {
            401: "认证失败，请检查应用凭据或令牌",
            403: "访问被拒绝，请检查 API 审批、应用权限或网络出口限制",
            429: "请求过于频繁，请降低频率并遵循 Retry-After 响应头",
        }[response.status_code]
        raise requests.HTTPError(f"{stage}：HTTP {response.status_code}，{reason}", response=response)
    response.raise_for_status()


def get_reddit_access_token(session, config):
    """
    为只读公开帖子请求获取应用级 OAuth 令牌。

    :param session: HTTP 会话
    :param config: 接口和认证配置
    :return: 访问令牌字符串
    """
    response = session.post(
        config["token_url"],
        auth=(config["REDDIT_CLIENT_ID"], config["REDDIT_CLIENT_SECRET"]),
        data={"grant_type": "client_credentials"},
        timeout=config["timeout"],
    )
    check_reddit_response(response, "获取 OAuth 令牌")
    token_data = response.json()
    if not token_data.get("access_token"):
        raise ValueError("令牌响应不含 access_token，请检查应用认证类型和访问权限")
    return token_data["access_token"]


def fetch_reddit_posts(subreddit=None, limit=None):
    """
    使用 OAuth 获取热门帖子，失败时抛出异常而非返回空数据。

    :param subreddit: 社区名称，为空时使用配置值
    :param limit: 帖子数量，取值 1 至 100，为空时使用配置值
    :return: 帖子字典列表
    """
    config = load_reddit_config()
    subreddit = config["subreddit"] if subreddit is None else subreddit
    limit = config["limit"] if limit is None else limit
    if not isinstance(subreddit, str) or not subreddit or not all(
        character.isascii() and (character.isalnum() or character == "_")
        for character in subreddit
    ):
        raise ValueError("subreddit 必须是社区名称，不含 r/ 前缀")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit 必须是 1 至 100 的整数")
    with requests.Session() as session:
        session.headers.update({"User-Agent": config["REDDIT_USER_AGENT"]})
        access_token = get_reddit_access_token(session, config)
        response = session.get(
            f"{config['api_base_url']}/r/{subreddit}/hot",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"limit": limit, "raw_json": 1},
            timeout=config["timeout"],
        )
        check_reddit_response(response, "获取热门帖子")
        data = response.json()

    posts = []

    for item in data["data"]["children"]:
        post = item["data"]

        posts.append({
            "platform": "reddit",
            "author": post.get("author"),
            "title": post.get("title"),
            "content": post.get("selftext"),
            "score": post.get("score"),
            "comments": post.get("num_comments"),
            "created_utc": post.get("created_utc"),
            "url": post.get("url")
        })

    return posts


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        posts = fetch_reddit_posts()
        logger.info("获取 Reddit 帖子成功，共 %s 条", len(posts))
        for post in posts[:5]:
            logger.info("帖子标题：%s；评分：%s", post["title"], post["score"])
    except (requests.RequestException, ValueError, KeyError, TypeError, OSError):
        logger.error("Reddit 抓取失败", exc_info=True)
        raise SystemExit(1)
