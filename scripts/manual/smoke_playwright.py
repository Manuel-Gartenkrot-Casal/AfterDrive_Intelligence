"""
Test script for AfterDrive Intelligence pipeline.
Uses Playwright to test the web application.
"""
import sys
import time
from playwright.sync_api import sync_playwright

def test_flask_api():
    """Test Flask API directly."""
    import requests
    
    print("=== Testing Flask API (port 5000) ===")
    
    # Test health endpoint
    try:
        r = requests.get("http://localhost:5000/health", timeout=5)
        print(f"Health: {r.status_code} - {r.json()}")
    except Exception as e:
        print(f"Health FAILED: {e}")
        return False
    
    # Test check-volume endpoint
    try:
        r = requests.get("http://localhost:5000/api/check-volume?keyword=autopartes", timeout=10)
        print(f"Volume: {r.status_code} - {r.json()}")
    except Exception as e:
        print(f"Volume FAILED: {e}")
    
    return True

def test_express_server():
    """Test Express server with Playwright."""
    print("\n=== Testing Express Server (port 3000) ===")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # Navigate to the app
        try:
            page.goto("http://localhost:3000", timeout=10000)
            page.wait_for_load_state("networkidle")
            
            # Take screenshot
            page.screenshot(path="scripts/manual/screenshot.png", full_page=True)
            print("Screenshot saved: scripts/manual/screenshot.png")
            
            # Check page title
            title = page.title()
            print(f"Page title: {title}")
            
            # Check if key elements exist
            stats_grid = page.locator(".stats-grid")
            print(f"Stats grid visible: {stats_grid.is_visible()}")
            
            # Check if API status is showing
            status_text = page.locator("#statusText")
            if status_text.is_visible():
                print(f"API Status: {status_text.text_content()}")
            
            # Check console for errors
            errors = []
            page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
            
            # Wait a bit for any console errors
            page.wait_for_timeout(2000)
            
            if errors:
                print(f"Console errors: {errors}")
            else:
                print("No console errors detected")
            
            browser.close()
            return True
            
        except Exception as e:
            print(f"Express test FAILED: {e}")
            browser.close()
            return False

def test_api_endpoints():
    """Test API endpoints through Express proxy."""
    import requests
    
    print("\n=== Testing API Endpoints through Express ===")
    
    endpoints = [
        ("GET", "/api/health"),
        ("GET", "/api/trusted-urls-stats"),
        ("GET", "/api/scraping-config"),
        ("GET", "/api/check-volume?keyword=autopartes"),
    ]
    
    for method, path in endpoints:
        try:
            if method == "GET":
                r = requests.get(f"http://localhost:3000{path}", timeout=10)
            else:
                r = requests.post(f"http://localhost:3000{path}", timeout=10)
            print(f"{method} {path}: {r.status_code}")
        except Exception as e:
            print(f"{method} {path}: FAILED - {e}")

if __name__ == "__main__":
    print("AfterDrive Intelligence - Pipeline Test")
    print("=" * 50)
    
    # Test Flask API
    flask_ok = test_flask_api()
    
    # Test Express server
    express_ok = test_express_server()
    
    # Test API endpoints
    test_api_endpoints()
    
    print("\n" + "=" * 50)
    print("Test Summary:")
    print(f"Flask API: {'PASS' if flask_ok else 'FAIL'}")
    print(f"Express Server: {'PASS' if express_ok else 'FAIL'}")
    
    if flask_ok and express_ok:
        print("\nAll tests passed!")
        sys.exit(0)
    else:
        print("\nSome tests failed!")
        sys.exit(1)
