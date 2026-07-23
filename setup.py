from pathlib import Path

from setuptools import find_packages, setup

this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

girder_version = "5.0.13.dev27"

setup(
    name="girder-jsonforms",
    long_description=long_description,
    long_description_content_type="text/markdown",
    version="2.1.1",
    description="Girder plugin adding forms based on JSON-editor",
    packages=find_packages(),
    data_files=[
        ("schemas", ["girder_jsonforms/schemas/datacite-v4.5.json"]),
    ],
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
        f"girder>={girder_version}",
        f"girder-worker>={girder_version}",
        "girder-wholetale>=2.0.11",
        f"girder-jobs>={girder_version}",
        "girder-sample-tracker>=2.0.0",  # Required for the sample tracker to test JSONForms
        f"girder-oauth>={girder_version}",
        "google-api-python-client",
        "google-auth-oauthlib",
        "jsondiff",
        "pandas",
        "openpyxl",
    ],
    entry_points={
        "console_scripts": [
            "girder-jsonforms-migrate-metadata-dates = "
            "girder_jsonforms.scripts.migrate_metadata_dates:main",
        ],
        "girder.plugin": ["jsonforms = girder_jsonforms:JSONFormsPlugin"],
        "girder_worker_plugins": [
            "jsonforms = girder_jsonforms.worker_plugin:JSONFormsWorkerPlugin"
        ],
    },
    zip_safe=False,
)
