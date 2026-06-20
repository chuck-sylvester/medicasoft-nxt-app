# Amazon Corretto 17 — macOS Apple Silicon Setup Guide

This guide covers detecting any existing Java installation, installing Amazon Corretto 17 on a macOS Apple Silicon (M1 / M2 / M3 / M4) machine, configuring the environment, and verifying that the installation works correctly for this project's Synthea requirement.

---

## Why Corretto 17

Amazon Corretto is a no-cost, production-ready distribution of OpenJDK maintained by AWS. It passes the Java SE TCK (Technology Compatibility Kit), meaning it is fully compatible with standard Java. Corretto 17 is a Long-Term Support (LTS) release — the same LTS line used across most enterprise Java deployments. Synthea requires Java 17+.

---

## Step 1 — Detect any existing Java installation

Run all three commands. Together they give a complete picture of what is on the machine.

```bash
# Is any Java on the PATH right now?
java -version

# List all JDKs macOS knows about (installed under /Library/Java/JavaVirtualMachines/)
/usr/libexec/java_home -V

# Confirm where the 'java' binary resolves to
which java
```

**Interpreting the output:**

| `java -version` output | Meaning |
|---|---|
| `command not found` or system dialog about installing Java | No JDK installed — go to [Step 3](#step-3--install-corretto-17) |
| Shows version 17 and `Corretto` in the string | Corretto 17 is already installed — go to [Step 4](#step-4--configure-java_home) to verify the environment |
| Shows version 17 with a different vendor (Temurin, Oracle, etc.) | A different JDK 17 is installed — read [Step 2A](#step-2a--a-non-corretto-jdk-17-is-installed) |
| Shows a version other than 17 (e.g., 11, 21) | A different Java version is installed — read [Step 2B](#step-2b--a-different-java-version-is-installed) |

`/usr/libexec/java_home -V` lists every JDK registered with macOS, even ones not on the current PATH. Use it to see the full inventory regardless of what `java -version` reports.

---

## Step 2 — If Java is already installed

### Step 2A — A non-Corretto JDK 17 is installed

macOS supports multiple JDKs installed simultaneously. There is no need to remove the existing JDK. Install Corretto 17 alongside it (Step 3), then point `JAVA_HOME` at Corretto 17 (Step 4). The existing JDK remains available and other tools that depend on it are unaffected.

### Step 2B — A different Java version is installed

Same approach: install Corretto 17 alongside the existing version (Step 3) and configure `JAVA_HOME` to select Corretto 17 (Step 4). macOS's `/usr/libexec/java_home` utility makes it straightforward to select a specific version without removing others.

If you want to remove the older JDK after confirming Corretto 17 works:

```bash
# List installed JDKs and their paths
/usr/libexec/java_home -V

# Remove a specific JDK (substitute the actual path from the listing above)
sudo rm -rf /Library/Java/JavaVirtualMachines/<jdk-folder-name>
```

Only remove a JDK if you are certain no other tool on the machine depends on it.

---

## Step 3 — Install Corretto 17

Two installation methods are provided. Homebrew is recommended — it handles the download, placement, and future upgrade management.

### Option A — Homebrew (recommended)

Homebrew installs the correct ARM64 (aarch64) build automatically on Apple Silicon.

```bash
# Install Corretto 17
brew install --cask corretto@17
```

Homebrew installs Corretto to:
```
/Library/Java/JavaVirtualMachines/amazon-corretto-17.jdk
```

> **Note:** Older Homebrew documentation and guides may reference `corretto17` (no `@`)
> and a `homebrew/cask-versions` tap. Both are obsolete — Homebrew migrated all versioned
> casks into the main tap and renamed them to the `@version` convention. The command above
> is the current correct form.

### Option B — Direct download from Amazon

Use this if Homebrew is not available or you prefer manual control.

1. Go to **https://aws.amazon.com/corretto/**
2. Click **Download Corretto 17**
3. On the downloads page, select:
   - **Operating system:** macOS
   - **Architecture:** `aarch64` — this is the native ARM64 build for Apple Silicon.
     Do **not** select `x86_64`; that build runs under Rosetta 2 emulation and is
     significantly slower.
4. Download the `.pkg` installer
5. Open the downloaded `.pkg` file and follow the installer prompts

The installer places the JDK in:
```
/Library/Java/JavaVirtualMachines/amazon-corretto-17.jdk
```

---

## Step 4 — Configure JAVA_HOME

macOS does not automatically set `JAVA_HOME`. Without it, some tools (including build systems and IDEs) cannot locate the JDK. Configure it in your shell profile.

**Confirm the Corretto 17 path:**

```bash
/usr/libexec/java_home -v 17
```

This should print something like:
```
/Library/Java/JavaVirtualMachines/amazon-corretto-17.jdk/Contents/Home
```

**Add to your shell profile:**

macOS uses zsh by default. Open `~/.zshrc` in any editor and add these two lines at the end:

```bash
# Java — Amazon Corretto 17
export JAVA_HOME=$(/usr/libexec/java_home -v 17)
export PATH=$JAVA_HOME/bin:$PATH
```

Using `$(/usr/libexec/java_home -v 17)` rather than a hardcoded path means the environment variable stays correct even if macOS reorganizes the JDK directory on an update.

**Apply the change to the current terminal session:**

```bash
source ~/.zshrc
```

---

## Step 5 — Verify the installation

Run each command and confirm the expected output.

```bash
# Java runtime version — must show 17.x.x and Corretto
java -version
```
Expected (version numbers will differ):
```
openjdk version "17.0.x" 202x-xx-xx LTS
OpenJDK Runtime Environment Corretto-17.0.x.x.x (build 17.0.x+x-LTS)
OpenJDK 64-Bit Server VM Corretto-17.0.x.x.x (build 17.0.x+x-LTS, mixed mode, sharing)
```

```bash
# Java compiler version — must match the runtime
javac -version
```
Expected:
```
javac 17.0.x
```

```bash
# JAVA_HOME — must resolve to the Corretto 17 path
echo $JAVA_HOME
```
Expected:
```
/Library/Java/JavaVirtualMachines/amazon-corretto-17.jdk/Contents/Home
```

```bash
# Confirm the architecture is ARM64 (native Apple Silicon — not Rosetta)
java -XshowSettings:property -version 2>&1 | grep "os.arch"
```
Expected:
```
os.arch = aarch64
```

If `os.arch` shows `x86_64`, the x86 build was installed. Remove it and reinstall using Option A or by downloading the `aarch64` package in Option B.

```bash
# Full JDK inventory — Corretto 17 should appear in the list
/usr/libexec/java_home -V
```

---

## Step 6 — Verify for Synthea

Synthea is the tool used in Phase 1 to generate US Core–profiled synthetic patient data. It requires Java 17+. Once you have downloaded `synthea-with-dependencies.jar`, verify it launches correctly under Corretto 17:

```bash
java -jar synthea-with-dependencies.jar --help
```

The help text should print without error. If you see `UnsupportedClassVersionError`, the `java` on PATH is older than 17 — re-check `java -version` and `echo $JAVA_HOME` to confirm the correct JDK is active.

---

## Troubleshooting

**`java -version` still shows the old JDK after adding to `~/.zshrc`**

The shell profile was not reloaded, or a system-level `/etc/paths` entry is taking
precedence. Run:

```bash
source ~/.zshrc
which java          # should point into the Corretto 17 path
java -version
```

If `which java` shows `/usr/bin/java` (the macOS stub), the `PATH` export in
`~/.zshrc` is not taking effect. Confirm the `export PATH=$JAVA_HOME/bin:$PATH` line
is present and that `source ~/.zshrc` ran without error.

**Multiple JDK 17 versions listed by `/usr/libexec/java_home -V`**

If both Corretto 17 and another JDK 17 are installed, `java_home -v 17` selects
whichever it finds first. To select Corretto 17 explicitly, use the full version string
from the `/usr/libexec/java_home -V` listing:

```bash
# Example — substitute the exact build string from your listing
export JAVA_HOME=$(/usr/libexec/java_home -v "17.0.x-amzn")
```

**Homebrew installed Corretto 21 instead of 17**

`brew install --cask corretto` (without a version) installs the latest Corretto release,
which is currently 21. Remove it and install the versioned cask:

```bash
brew uninstall --cask corretto
brew install --cask corretto@17
```
