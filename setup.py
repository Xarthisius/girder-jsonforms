from pathlib import Path

from setuptools import find_packages, setup

this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

setup(
    name="girder-jsonforms",
    long_description=long_description,
    long_description_content_type="text/markdown",
    version="2.0.3",
    description="Girder plugin adding forms based on JSON-editor",
    packages=find_packages(),
    include_package_data=True,
    license="BSD-3-Clause",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Web Environment",
        "License :: OSI Approved :: BSD License",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
    ],
    python_requires=">=3.10",
    setup_requires=["setuptools-git"],
    install_requires=[
        "girder>=5.0.0a5.dev0",
        "google-api-python-client",
        "google-auth-oauthlib",
        "pandas",
    ],
    entry_points={"girder.plugin": ["jsonforms = girder_jsonforms:JSONFormsPlugin"]},
    zip_safe=False,
)
