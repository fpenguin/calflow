import yaml
from parser import extract_urls, extract_hashtags, extract_alert_offset

def run():
    with open("tests/cases/basic.yaml") as f:
        cases = yaml.safe_load(f)

    for case in cases:
        text = case["input"]

        urls = extract_urls(text)
        tags = list(extract_hashtags(text))
        alert = extract_alert_offset(tags)

        expected = case["expected"]

        print(f"\nTEST: {case['name']}")

        if "urls" in expected:
            assert urls == expected["urls"], f"URLs mismatch: {urls}"

        if "tags" in expected:
            assert sorted(tags) == sorted(expected["tags"]), f"Tags mismatch: {tags}"

        if "alert" in expected:
            assert alert == expected["alert"], f"Alert mismatch: {alert}"

        print("✅ PASS")


if __name__ == "__main__":
    run()