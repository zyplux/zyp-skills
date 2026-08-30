# 1. [Bumping a skill release version](test_1_release-bump.py)

## 1.1 bumping every version surface of a skill

### 1.1.1 updates skill md py module and package json together

## 1.2 refusing malformed version state

### 1.2.1 rejects a skill md version that is not semver

### 1.2.2 rejects a skill md with no version field

## 1.3 requiring the git tool

### 1.3.1 fails when git is missing from path

## 1.4 requiring a version bump for changed skills

### 1.4.1 rejects a changed skill whose version still matches its latest tag

### 1.4.2 accepts a changed skill whose version is ahead of its latest tag

### 1.4.3 rejects a skill version below its latest tag

### 1.4.4 accepts a new skill without a release tag

### 1.4.5 check command reports the release violation
