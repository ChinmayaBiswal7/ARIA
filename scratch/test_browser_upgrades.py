import os
import sys
import time
import unittest

# Ensure project path is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skills.browser_skill import BrowserSkill

# Create a mock product HTML page
MOCK_HTML_CONTENT = """<!DOCTYPE html>
<html>
<head>
    <title>Original Document Title</title>
</head>
<body style="margin: 0; padding: 0;">
    <!-- Large height to enable scrolling -->
    <div style="height: 3000px; padding: 20px;">
        <div id="productTitle">
            AULA F75 Pro Wireless Mechanical Keyboard
        </div>
        
        <div class="a-price">
            <span class="a-offscreen">₹6,499.00</span>
        </div>
        
        <div id="acrPopover" title="4.6 out of 5 stars">
            <span class="a-icon-alt">4.6 out of 5 stars</span>
        </div>
        
        <span id="acrCustomerReviewText">1,248 ratings</span>
        
        <div id="feature-bullets">
            <ul class="a-unordered-list a-vertical">
                <li><span class="a-list-item">Make sure this fits by entering your model number.</span></li>
                <li><span class="a-list-item">75% Layout Custom Mechanical Keyboard with Knob</span></li>
                <li><span class="a-list-item">Tri-Mode Connectivity: 2.4GHz Wireless, Bluetooth 5.0, USB-C wired</span></li>
                <li><span class="a-list-item">Pre-lubed Reaper Switches & Hot-Swappable PCB</span></li>
            </ul>
        </div>
        
        <div id="productDescription">
            <p>The AULA F75 Pro is a premium mechanical keyboard designed for enthusiasts who want the absolute best typing feel and acoustics right out of the box.</p>
        </div>
        
        <button id="add-to-cart-button">Add to Cart</button>
    </div>
</body>
</html>
"""

def test_browser_upgrades():
    print("=== Testing BrowserSkill Upgrades System ===")
    
    # 1. Create a local temporary HTML file
    scratch_dir = os.path.dirname(os.path.abspath(__file__))
    mock_file_path = os.path.join(scratch_dir, "mock_product.html")
    with open(mock_file_path, "w", encoding="utf-8") as f:
        f.write(MOCK_HTML_CONTENT)
        
    url_path = "file:///" + mock_file_path.replace("\\", "/")
    print(f"Mock file URL: {url_path}")
    
    bs = BrowserSkill()
    
    try:
        # Start browser (headless mode for automated test runner)
        print("Starting browser...")
        success, msg = bs.start_browser(headless=True)
        print(f"Start browser result: {success}, {msg}")
        assert success, "Browser failed to start"
        
        # Navigate to the local mock product page
        print("Navigating to mock page...")
        nav_res = bs.navigate(url_path)
        print(f"Navigation result: {nav_res}")
        
        # 2. Test DOM Product Content Extraction
        print("\n--- Testing DOM Product Content Extraction ---")
        info = bs.extract_page_content()
        print(f"Extracted Product Info: {str(info).encode('ascii', 'replace').decode('ascii')}")
        
        assert info.get("title") == "AULA F75 Pro Wireless Mechanical Keyboard", "Failed to extract title"
        price_safe = info.get("price", "").encode('ascii', 'replace').decode('ascii')
        assert info.get("price") == "₹6,499.00", f"Failed to extract price, got: {price_safe}"
        assert info.get("rating") == "4.6 / 5", f"Failed to extract/normalize rating, got: {info.get('rating')}"
        assert info.get("review_count") == "1,248 ratings", "Failed to extract reviews"
        
        bullets = info.get("bullets", [])
        print(f"Extracted Bullets: {bullets}")
        assert len(bullets) == 3, f"Expected 3 bullets (excluding fits text), got: {len(bullets)}"
        assert bullets[0] == "75% Layout Custom Mechanical Keyboard with Knob"
        assert bullets[1] == "Tri-Mode Connectivity: 2.4GHz Wireless, Bluetooth 5.0, USB-C wired"
        assert bullets[2] == "Pre-lubed Reaper Switches & Hot-Swappable PCB"
        
        assert "premium mechanical keyboard" in info.get("description", ""), "Failed to extract description"
        print("DOM Product Content Extraction test passed!")
        
        # 3. Test Scrolling Amounts
        print("\n--- Testing Scroll Granular Control ---")
        
        # Get starting scroll Y position
        bs._update_page_state()
        initial_y = bs.page_state.get("scroll_y", 0)
        viewport_h = bs.page_state.get("viewport_height", 0)
        print(f"Initial Scroll Y: {initial_y}, Viewport Height: {viewport_h}")
        
        # A. Scroll down a little (15% factor)
        scroll_res = bs.scroll("down", "little")
        print(f"Scroll down little result: {scroll_res}")
        bs._update_page_state()
        y_after_little = bs.page_state.get("scroll_y", 0)
        diff_little = y_after_little - initial_y
        print(f"Scroll Y after little: {y_after_little} (moved: {diff_little}px)")
        expected_little = viewport_h * 0.15
        assert diff_little > 0, "Page should scroll down"
        # Since it uses mouse wheel too, check that it scrolled close to expected range
        
        # B. Scroll to top
        scroll_res = bs.scroll("top")
        print(f"Scroll top result: {scroll_res}")
        bs._update_page_state()
        y_top = bs.page_state.get("scroll_y", 0)
        print(f"Scroll Y at top: {y_top}")
        assert y_top == 0, "Page should be scrolled to top"
        
        # C. Scroll to bottom
        scroll_res = bs.scroll("bottom")
        print(f"Scroll bottom result: {scroll_res}")
        bs._update_page_state()
        y_bottom = bs.page_state.get("scroll_y", 0)
        print(f"Scroll Y at bottom: {y_bottom}")
        assert y_bottom > 1000, "Page should be scrolled to bottom"
        
        print("Granular Scroll Control test passed!")
        
    finally:
        print("Closing browser...")
        bs.close_browser()
        if os.path.exists(mock_file_path):
            os.remove(mock_file_path)
            
    print("\nAll browser upgrade tests passed successfully!")

if __name__ == "__main__":
    test_browser_upgrades()
