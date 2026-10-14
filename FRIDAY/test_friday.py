import subprocess
import time
import os
import signal

def main():
    print("Starting FRIDAY...")
    proc = subprocess.Popen([r".venv\Scripts\python.exe", "main.py"], 
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
    
    print("Listening to FRIDAY for 15 seconds (please speak!)...")
    time.sleep(15)
    print("Terminating FRIDAY...")
    
    # Send SIGTERM
    if os.name == 'nt':
        proc.send_signal(signal.CTRL_C_EVENT)
    else:
        proc.terminate()
        
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        
    out, _ = proc.communicate()
    
    with open("friday_test_output.log", "w", encoding="utf-8") as f:
        f.write(out)
        
    print("Done. Output saved to friday_test_output.log.")

if __name__ == "__main__":
    main()
