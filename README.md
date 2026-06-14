# chatgpt gen

## what is this?

A Python-based OpenAI account generator that automates account creation using Mailcow email inboxes and locally generated Sentinel challenge tokens.

Unlike browser automation tools, this project reproduces the required Sentinel proof-of-work and challenge flows directly in Python, eliminating the need for a browser.
## preview

https://raw.githubusercontent.com/<your-username>/<your-repo>/main/preview.mp4

Features:

* Generates Sentinel requirement and enforcement tokens locally
* Creates Mailcow inboxes automatically
* Retrieves OTP codes through IMAP
* Completes the signup flow
* Returns a valid session token
* Supports proxies and multithreading(Multithreading is still pending i will implement it later)
* No browser automation required

---

## how it works

The `SDK` class in `sdk.py` replicates the behavior of OpenAI's Sentinel SDK entirely in Python.

A custom virtual machine implements 36 opcodes that mirror the behavior of the browser-side SDK. It decodes challenge payloads, executes instruction queues, and returns the required challenge responses.

Proof-of-work challenges are solved locally using FNV and Murmur hash calculations. The solver brute-forces values until the required difficulty target is satisfied.

### account creation flow

1. Capture a browser fingerprint using `fp_scraper.py`
2. Load the fingerprint into the SDK
3. Generate a Sentinel requirements token
4. Request chat requirements from OpenAI
5. Solve proof-of-work challenges if required
6. Execute challenge payloads through the VM when necessary
7. Submit the signup request
8. Retrieve the OTP from Mailcow via IMAP
9. Verify the account
10. Extract and save the session token

---

## installation

### requirements

* Python 3.11+
* requests

### configuration

Create a `config.json` file:

```json
{
  "mailcows": [
    {
      "domain": "yourdomain.com",
      "api_url": "https://mail.yourdomain.com/api/v1/add/mailbox",
      "api_key": "your-mailcow-api-key"
    }
  ],
  "fp_dir": "fp",
  "sessions_file": "done.txt",
  "proxies": false,
  "proxies_file": "proxies.txt"
}
```

---

## capturing fingerprints

Start the fingerprint collector:

```bash
python3 fp_scraper.py
```

Open:

```text
http://127.0.0.1:8765/
```

Click **Capture** and save fingerprints from any browser or profile you want to use.

Fingerprint files will be stored inside the `fp/` directory.

---

## running the generator

```bash
python3 main.py
```

The script will prompt for the number of accounts to create and will save results to:

```text
done.txt
```

Output format:

```text
email:password:session_token
```

---

## proxy support

Enable proxies in `config.json`:

```json
{
  "proxies": true
}
```

Add proxies to `proxies.txt`:

```text
http://user:pass@host:port
socks5://user:pass@host:port
```

A random proxy is selected for each account.

---

## project structure

| File            | Description                                                                   |
| --------------- | ----------------------------------------------------------------------------- |
| `sdk.py`        | Sentinel SDK implementation, VM, proof-of-work solver, and challenge handling |
| `main.py`       | Main account generation workflow                                              |
| `fp_scraper.py` | Browser fingerprint collection server                                         |
| `mail.py`       | Mailcow mailbox creation and management                                       |

---

## sdk overview

### initialization

```python
SDK(fp_path)
```

Initialize the SDK using a directory containing fingerprint files.

### available methods

```python
sdk.load_fps()
```

Load fingerprint files.

```python
sdk.make_fp(data)
```

Create an `FP` instance from raw fingerprint data.

```python
sdk.make_prover(fp)
```

Create a proof-of-work solver.

```python
sdk.make_host(fp)
```

Create a host environment.

```python
sdk.full_init(did, fp, sess, base, flow)
```

Perform complete SDK initialization.

```python
sdk.exec_vm(dx, key)
```

Execute a challenge payload through the VM.

---

## error handling

* Mail server failures are reported and account creation stops.
* Invalid or corrupted fingerprint files are skipped.
* Failed account creation attempts are logged and processing continues.

---

## backwards compatibility

Legacy imports remain supported:

```python
BrowserFingerprint = FP
ProofGenerator = Prover
SentinelClient = Sentinel
HostEnv = Host
```

---

## disclaimer

This project is provided for educational and research purposes only.

The authors assume no responsibility for misuse of the software or for any actions taken using it. The purpose of this project is to study challenge systems, proof-of-work mechanisms, and browser fingerprinting techniques.

Use it responsibly and in accordance with applicable laws and service terms.

---

## license

MIT License

## Alert

This project is open source. Feel free to learn from it and modify it, but don't sell it or pretend you made it. Please give credit where it's due.
