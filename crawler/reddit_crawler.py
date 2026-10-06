import requests


def fetch_reddit_posts(subreddit="Bitcoin", limit=20):
    url = f"https://www.reddit.com/r/{subreddit}/hot.json"

    headers = {
        "User-Agent": "SocialAlpha/1.0"
    }

    params = {
        "limit": limit
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=10
    )

    response.raise_for_status()

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
    posts = fetch_reddit_posts()

    for post in posts[:5]:
        print(post)
        print("-" * 80)