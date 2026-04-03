"""Setup script for AutoTrader Deal Finder."""

from setuptools import find_packages, setup

setup(
    name="autotrader-deal-finder",
    version="1.0.0",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "playwright>=1.40.0",
        "beautifulsoup4>=4.12.0",
        "lxml>=5.0.0",
        "fastapi>=0.109.0",
        "uvicorn>=0.27.0",
        "jinja2>=3.1.0",
        "click>=8.1.0",
        "httpx>=0.26.0",
        "tenacity>=8.2.0",
    ],
    entry_points={
        "console_scripts": [
            "autotrader=autotrader.cli:main",
        ],
    },
    python_requires=">=3.11",
)
