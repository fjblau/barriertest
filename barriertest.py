import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import pandas as pd
from urllib.parse import urlparse
import base64
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from io import BytesIO

st.set_page_config(
    page_title="Web Accessibility Analyzer",
    page_icon="♿",
    layout="wide"
)

def is_valid_url(url):
    """Check if the URL is valid."""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False

def fetch_website_content(url):
    """Fetch the HTML content of the website."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.text
    except requests.exceptions.HTTPError as e:
        st.error(f"HTTP Error: {e}")
    except requests.exceptions.ConnectionError:
        st.error("Connection Error: Failed to establish a connection to the server.")
    except requests.exceptions.Timeout:
        st.error("Timeout Error: The request timed out.")
    except requests.exceptions.RequestException as e:
        st.error(f"Error: {e}")
    return None

def check_img_alt_text(soup):
    """Check if all images have alt text."""
    images = soup.find_all('img')
    missing_alt = []
    
    for img in images:
        if not img.get('alt') or img.get('alt').strip() == '':
            # Get image src or a placeholder if not available
            src = img.get('src', 'No source')
            missing_alt.append(src)
    
    return {
        'total_images': len(images),
        'images_with_alt': len(images) - len(missing_alt),
        'missing_alt': missing_alt
    }

def check_heading_structure(soup):
    """Check if the heading structure is properly organized."""
    headings = []
    heading_levels = {'h1': 0, 'h2': 0, 'h3': 0, 'h4': 0, 'h5': 0, 'h6': 0}
    issues = []
    
    for level in range(1, 7):
        tags = soup.find_all(f'h{level}')
        heading_levels[f'h{level}'] = len(tags)
        
        for tag in tags:
            headings.append({
                'level': level,
                'text': tag.get_text(strip=True)
            })
    
    # Check if there's exactly one h1
    if heading_levels['h1'] == 0:
        issues.append("No H1 heading found. Each page should have exactly one H1 heading.")
    elif heading_levels['h1'] > 1:
        issues.append(f"Multiple H1 headings found ({heading_levels['h1']}). Each page should have exactly one H1 heading.")
    
    # Check for heading level skips
    prev_level = 0
    for heading in headings:
        level = heading['level']
        if level > prev_level + 1 and prev_level > 0:
            issues.append(f"Heading level skip: H{prev_level} to H{level}")
        prev_level = level if level > prev_level else prev_level
    
    return {
        'heading_levels': heading_levels,
        'headings': headings,
        'issues': issues
    }

def check_color_contrast(html_content):
    """
    Extract color information to help identify potential contrast issues.
    Note: This is a simplified check, as full contrast checking requires rendering the page.
    """
    # Extract style attributes and CSS properties
    color_props = []
    
    # Extract inline styles
    style_pattern = r'style=["\']([^"\']*)["\']'
    style_matches = re.findall(style_pattern, html_content)
    
    for style in style_matches:
        # Look for color and background-color properties
        color_match = re.search(r'color:\s*([^;]+)', style)
        bg_color_match = re.search(r'background-color:\s*([^;]+)', style)
        
        if color_match:
            color_props.append(f"Text color: {color_match.group(1)}")
        if bg_color_match:
            color_props.append(f"Background color: {bg_color_match.group(1)}")
    
    # Extract CSS class names for further analysis
    class_pattern = r'class=["\']([^"\']*)["\']'
    class_matches = re.findall(class_pattern, html_content)
    common_classes = {}
    
    for classes in class_matches:
        for cls in classes.split():
            if cls in common_classes:
                common_classes[cls] += 1
            else:
                common_classes[cls] = 1
    
    # Filter for most common classes
    common_classes = {k: v for k, v in sorted(common_classes.items(), key=lambda item: item[1], reverse=True)[:10]}
    
    return {
        'color_properties': color_props[:20],  # Limit to first 20 to avoid overwhelming output
        'common_classes': common_classes
    }

def check_form_accessibility(soup):
    """Check if forms are accessible."""
    forms = soup.find_all('form')
    form_issues = []
    
    for i, form in enumerate(forms, 1):
        form_data = {
            'form_number': i,
            'issues': []
        }
        
        # Check for inputs without labels
        inputs = form.find_all(['input', 'textarea', 'select'])
        for input_tag in inputs:
            input_id = input_tag.get('id')
            input_type = input_tag.get('type', 'text')
            
            # Skip hidden, submit, button, and image input types
            if input_type in ['hidden', 'submit', 'button', 'image']:
                continue
            
            # Check if input has an id and a corresponding label
            if input_id:
                label = form.find('label', attrs={'for': input_id})
                if not label:
                    form_data['issues'].append(f"Input '{input_id}' (type: {input_type}) has no associated label.")
            else:
                # Check if the input is wrapped in a label
                parent_label = input_tag.find_parent('label')
                if not parent_label:
                    # Use name, placeholder or type to identify the input
                    identifier = input_tag.get('name') or input_tag.get('placeholder') or input_type
                    form_data['issues'].append(f"Input '{identifier}' has no associated label.")
        
        if form_data['issues']:
            form_issues.append(form_data)
    
    return {
        'total_forms': len(forms),
        'forms_with_issues': len(form_issues),
        'form_issues': form_issues
    }

def check_landmarks_aria(soup):
    """Check for proper use of landmarks and ARIA attributes."""
    # Look for landmark roles and HTML5 semantic elements
    landmarks = {
        'header/banner': len(soup.find_all('header')) + len(soup.find_all(attrs={'role': 'banner'})),
        'nav/navigation': len(soup.find_all('nav')) + len(soup.find_all(attrs={'role': 'navigation'})),
        'main': len(soup.find_all('main')) + len(soup.find_all(attrs={'role': 'main'})),
        'aside/complementary': len(soup.find_all('aside')) + len(soup.find_all(attrs={'role': 'complementary'})),
        'footer/contentinfo': len(soup.find_all('footer')) + len(soup.find_all(attrs={'role': 'contentinfo'})),
        'section': len(soup.find_all('section')),
        'article': len(soup.find_all('article')),
        'figure': len(soup.find_all('figure')),
    }
    
    # Check for common ARIA attributes - safer approach
    aria_attrs = {}
    for tag in soup.find_all():
        for attr_name in tag.attrs:
            if isinstance(attr_name, str) and attr_name.startswith('aria-'):
                if attr_name in aria_attrs:
                    aria_attrs[attr_name] += 1
                else:
                    aria_attrs[attr_name] = 1
    
    issues = []
    if landmarks['main'] == 0:
        issues.append("No main content area defined. Use <main> element or role='main'.")
    if landmarks['nav/navigation'] == 0:
        issues.append("No navigation landmark found. Use <nav> element or role='navigation'.")
    
    return {
        'landmarks': landmarks,
        'aria_attributes': aria_attrs,
        'issues': issues
    }

def check_keyboard_accessibility(soup, html_content):
    """Check for potential keyboard accessibility issues."""
    issues = []
    
    # Check for elements with onclick but no keyboard equivalent
    onclick_elements = soup.find_all(attrs={"onclick": True})
    for element in onclick_elements:
        # Check if the element has keyboard handlers like onkeypress, onkeydown, or is naturally focusable
        if not (element.has_attr('onkeypress') or element.has_attr('onkeydown') or element.has_attr('onkeyup') or
                element.name in ['a', 'button', 'input', 'select', 'textarea'] or
                element.has_attr('tabindex')):
            element_id = element.get('id', '')
            element_class = element.get('class', '')
            issues.append(f"Element with onclick handler may not be keyboard accessible: {element.name} (id: {element_id}, class: {' '.join(element_class) if isinstance(element_class, list) else element_class})")
    
    # Check for tabindex > 0 (which can cause keyboard navigation issues)
    # Safer approach to find elements with tabindex
    tabindex_elements = []
    for element in soup.find_all():
        if element.has_attr('tabindex'):
            try:
                tabindex_value = element['tabindex']
                if tabindex_value and tabindex_value.isdigit() and int(tabindex_value) > 0:
                    tabindex_elements.append(element)
            except (AttributeError, ValueError):
                # Skip elements that cause errors
                pass
                
    for element in tabindex_elements:
        element_id = element.get('id', '')
        element_class = element.get('class', '')
        issues.append(f"Element with tabindex > 0 found, which can disrupt keyboard navigation: {element.name} (id: {element_id}, class: {' '.join(element_class) if isinstance(element_class, list) else element_class})")
    
    return {
        'keyboard_issues': issues,
        'onclick_elements': len(onclick_elements),
        'problematic_tabindex': len(tabindex_elements)
    }

def check_tables(soup):
    """Check if tables are accessible."""
    tables = soup.find_all('table')
    table_issues = []
    
    for i, table in enumerate(tables, 1):
        table_data = {
            'table_number': i,
            'issues': []
        }
        
        # Check for caption
        if not table.find('caption'):
            table_data['issues'].append("Table lacks a caption element.")
        
        # Check for table headers
        th_elements = table.find_all('th')
        if not th_elements:
            table_data['issues'].append("Table lacks header cells (th elements).")
        
        # Check for scope attributes in headers
        for th in th_elements:
            if not th.has_attr('scope'):
                header_text = th.get_text(strip=True)
                table_data['issues'].append(f"Table header '{header_text[:20]}...' lacks scope attribute.")
        
        if table_data['issues']:
            table_issues.append(table_data)
    
    return {
        'total_tables': len(tables),
        'tables_with_issues': len(table_issues),
        'table_issues': table_issues
    }

def check_language(soup):
    """Check if the language is specified."""
    html_tag = soup.find('html')
    if html_tag and html_tag.has_attr('lang'):
        return {
            'language_specified': True,
            'language': html_tag['lang']
        }
    return {
        'language_specified': False,
        'language': None
    }

def check_links(soup):
    """Check links for accessibility issues."""
    links = soup.find_all('a')
    link_issues = []
    
    # Common non-descriptive link texts
    non_descriptive = ['click here', 'read more', 'more', 'link', 'here', 'this', 'this link', 'learn more']
    
    for link in links:
        link_text = link.get_text(strip=True)
        
        if not link_text:
            # Check if there's an image with alt text
            img = link.find('img')
            if img and img.has_attr('alt') and img['alt'].strip():
                continue
            link_issues.append({
                'url': link.get('href', '#'),
                'issue': "Link has no text content"
            })
        elif link_text.lower() in non_descriptive:
            link_issues.append({
                'url': link.get('href', '#'),
                'issue': f"Non-descriptive link text: '{link_text}'"
            })
        elif len(link_text) < 4:
            link_issues.append({
                'url': link.get('href', '#'),
                'issue': f"Very short link text: '{link_text}'"
            })
    
    # Check for links that open in new windows without warning
    new_window_links = soup.find_all('a', attrs={'target': '_blank'})
    for link in new_window_links:
        link_text = link.get_text(strip=True)
        has_warning = any(warning in link_text.lower() for warning in ['new window', 'new tab']) or link.find('span', class_='sr-only')
        if not has_warning:
            link_issues.append({
                'url': link.get('href', '#'),
                'issue': f"Link opens in new window without warning: '{link_text}'"
            })
    
    return {
        'total_links': len(links),
        'links_with_issues': len(link_issues),
        'link_issues': link_issues[:20]  # Limit to first 20 to avoid overwhelming output
    }

def analyze_accessibility(url):
    """Analyze the accessibility of a website."""
    html_content = fetch_website_content(url)
    if not html_content:
        return None
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    results = {
        'url': url,
        'img_alt_text': check_img_alt_text(soup),
        'heading_structure': check_heading_structure(soup),
        'color_contrast': check_color_contrast(html_content),
        'form_accessibility': check_form_accessibility(soup),
        'landmarks_aria': check_landmarks_aria(soup),
        'keyboard_accessibility': check_keyboard_accessibility(soup, html_content),
        'tables': check_tables(soup),
        'language': check_language(soup),
        'links': check_links(soup)
    }
    
    return results

def calculate_score(results):
    """Calculate an accessibility score based on the results."""
    score = 100
    deductions = []
    
    # Image alt text
    img_alt = results['img_alt_text']
    if img_alt['total_images'] > 0:
        alt_percentage = img_alt['images_with_alt'] / img_alt['total_images']
        if alt_percentage < 1:
            score_deduction = min(15, int(15 * (1 - alt_percentage)))
            score -= score_deduction
            deductions.append(f"Missing alt text: -{score_deduction} points")
    
    # Heading structure
    heading_issues = results['heading_structure']['issues']
    if heading_issues:
        score_deduction = min(15, 5 * len(heading_issues))
        score -= score_deduction
        deductions.append(f"Heading structure issues: -{score_deduction} points")
    
    # Form accessibility
    form_issues = results['form_accessibility']['forms_with_issues']
    if form_issues > 0:
        score_deduction = min(15, 5 * form_issues)
        score -= score_deduction
        deductions.append(f"Form accessibility issues: -{score_deduction} points")
    
    # Landmarks and ARIA
    landmark_issues = results['landmarks_aria']['issues']
    if landmark_issues:
        score_deduction = min(10, 5 * len(landmark_issues))
        score -= score_deduction
        deductions.append(f"Landmark/ARIA issues: -{score_deduction} points")
    
    # Keyboard accessibility
    keyboard_issues = len(results['keyboard_accessibility']['keyboard_issues'])
    if keyboard_issues > 0:
        score_deduction = min(15, 3 * keyboard_issues)
        score -= score_deduction
        deductions.append(f"Keyboard accessibility issues: -{score_deduction} points")
    
    # Tables
    table_issues = results['tables']['tables_with_issues']
    if table_issues > 0:
        score_deduction = min(10, 3 * table_issues)
        score -= score_deduction
        deductions.append(f"Table accessibility issues: -{score_deduction} points")
    
    # Language
    if not results['language']['language_specified']:
        score -= 5
        deductions.append("Language not specified: -5 points")
    
    # Links
    link_issues = results['links']['links_with_issues']
    if link_issues > 0:
        score_deduction = min(15, int(15 * min(1, link_issues / results['links']['total_links'])))
        score -= score_deduction
        deductions.append(f"Link accessibility issues: -{score_deduction} points")
    
    # Ensure score is between 0 and 100
    score = max(0, min(100, score))
    
    return {
        'score': score,
        'deductions': deductions
    }

def get_score_color(score):
    """Return a color based on the score."""
    if score >= 90:
        return "green"
    elif score >= 70:
        return "orange"
    else:
        return "red"

def create_pdf_report(results, score_results):
    """Create a PDF report of the accessibility analysis."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=72)
    
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='Center', alignment=1))
    
    # Create the content for the PDF
    content = []
    
    # Title
    title = Paragraph(f"Web Accessibility Report for {results['url']}", styles['Title'])
    content.append(title)
    content.append(Spacer(1, 0.25*inch))
    
    # Score
    score = score_results['score']
    score_color = colors.green if score >= 90 else colors.orange if score >= 70 else colors.red
    
    score_text = Paragraph(f"<font color={'#006400' if score >= 90 else '#FFA500' if score >= 70 else '#FF0000'}>Accessibility Score: {score}/100</font>", styles['Heading1'])
    content.append(score_text)
    content.append(Spacer(1, 0.2*inch))
    
    # Score Deductions
    if score_results['deductions']:
        content.append(Paragraph("Score Deductions:", styles['Heading2']))
        for deduction in score_results['deductions']:
            content.append(Paragraph(f"• {deduction}", styles['Normal']))
        content.append(Spacer(1, 0.2*inch))
    
    # Summary Section
    content.append(Paragraph("Accessibility Summary", styles['Heading1']))
    content.append(Spacer(1, 0.1*inch))
    
    # Images
    content.append(Paragraph("Images", styles['Heading2']))
    if results['img_alt_text']['total_images'] > 0:
        alt_percentage = (results['img_alt_text']['images_with_alt'] / results['img_alt_text']['total_images']) * 100
        content.append(Paragraph(f"Total images: {results['img_alt_text']['total_images']}", styles['Normal']))
        content.append(Paragraph(f"Images with alt text: {results['img_alt_text']['images_with_alt']} ({alt_percentage:.1f}%)", styles['Normal']))
        
        if results['img_alt_text']['missing_alt']:
            content.append(Paragraph("Images missing alt text (up to 5 shown):", styles['Normal']))
            for src in results['img_alt_text']['missing_alt'][:5]:
                content.append(Paragraph(f"• {src[:100]}..." if len(src) > 100 else f"• {src}", styles['Normal']))
    else:
        content.append(Paragraph("No images found on the page.", styles['Normal']))
    
    content.append(Spacer(1, 0.2*inch))
    
    # Headings
    content.append(Paragraph("Headings", styles['Heading2']))
    headings = results['heading_structure']
    
    # Create a table for heading counts
    heading_data = [["Heading Level", "Count"]]
    for level, count in headings['heading_levels'].items():
        heading_data.append([level.upper(), str(count)])
    
    heading_table = Table(heading_data, colWidths=[1.5*inch, 1*inch])
    heading_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    content.append(heading_table)
    content.append(Spacer(1, 0.1*inch))
    
    if headings['issues']:
        content.append(Paragraph("Heading structure issues:", styles['Normal']))
        for issue in headings['issues']:
            content.append(Paragraph(f"• {issue}", styles['Normal']))
    
    content.append(Spacer(1, 0.2*inch))
    
    # Language
    content.append(Paragraph("Language", styles['Heading2']))
    lang_results = results['language']
    if lang_results['language_specified']:
        content.append(Paragraph(f"Language specified: {lang_results['language']}", styles['Normal']))
    else:
        content.append(Paragraph("❌ Language not specified. The 'lang' attribute should be added to the HTML element.", styles['Normal']))
    
    content.append(Spacer(1, 0.2*inch))
    
    # Landmarks & ARIA
    content.append(Paragraph("Landmarks & ARIA", styles['Heading2']))
    landmark_data = [["Landmark Type", "Count"]]
    for landmark, count in results['landmarks_aria']['landmarks'].items():
        landmark_data.append([landmark, str(count)])
    
    landmark_table = Table(landmark_data, colWidths=[2*inch, 1*inch])
    landmark_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    content.append(landmark_table)
    content.append(Spacer(1, 0.1*inch))
    
    if results['landmarks_aria']['issues']:
        content.append(Paragraph("Landmark issues:", styles['Normal']))
        for issue in results['landmarks_aria']['issues']:
            content.append(Paragraph(f"• {issue}", styles['Normal']))
    
    content.append(Spacer(1, 0.2*inch))
    
    # Forms
    content.append(Paragraph("Forms", styles['Heading2']))
    form_results = results['form_accessibility']
    content.append(Paragraph(f"Total forms: {form_results['total_forms']}", styles['Normal']))
    content.append(Paragraph(f"Forms with issues: {form_results['forms_with_issues']}", styles['Normal']))
    
    if form_results['forms_with_issues'] > 0:
        content.append(Paragraph("Form accessibility issues:", styles['Normal']))
        for form in form_results['form_issues'][:3]:  # Limit to first 3 forms
            content.append(Paragraph(f"Form #{form['form_number']}:", styles['Normal']))
            for issue in form['issues'][:5]:  # Limit to first 5 issues per form
                content.append(Paragraph(f"• {issue}", styles['Normal']))
    
    content.append(Spacer(1, 0.2*inch))
    
    # Links
    content.append(Paragraph("Links", styles['Heading2']))
    link_results = results['links']
    content.append(Paragraph(f"Total links: {link_results['total_links']}", styles['Normal']))
    content.append(Paragraph(f"Links with issues: {link_results['links_with_issues']}", styles['Normal']))
    
    if link_results['links_with_issues'] > 0:
        content.append(Paragraph("Link accessibility issues (up to 5 shown):", styles['Normal']))
        for issue in link_results['link_issues'][:5]:
            issue_url = issue['url']
            issue_url = issue_url[:50] + "..." if len(issue_url) > 50 else issue_url
            content.append(Paragraph(f"• {issue['issue']} ({issue_url})", styles['Normal']))
    
    content.append(Spacer(1, 0.2*inch))
    
    # Keyboard Accessibility
    content.append(Paragraph("Keyboard Accessibility", styles['Heading2']))
    keyboard_results = results['keyboard_accessibility']
    content.append(Paragraph(f"Elements with onclick handlers: {keyboard_results['onclick_elements']}", styles['Normal']))
    content.append(Paragraph(f"Elements with problematic tabindex: {keyboard_results['problematic_tabindex']}", styles['Normal']))
    
    if keyboard_results['keyboard_issues']:
        content.append(Paragraph("Issues (up to 5 shown):", styles['Normal']))
        for issue in keyboard_results['keyboard_issues'][:5]:
            content.append(Paragraph(f"• {issue}", styles['Normal']))
    
    content.append(Spacer(1, 0.2*inch))
    
    # Tables
    content.append(Paragraph("Table Accessibility", styles['Heading2']))
    table_results = results['tables']
    content.append(Paragraph(f"Total tables: {table_results['total_tables']}", styles['Normal']))
    content.append(Paragraph(f"Tables with issues: {table_results['tables_with_issues']}", styles['Normal']))
    
    if table_results['tables_with_issues'] > 0:
        content.append(Paragraph("Issues (up to 3 tables shown):", styles['Normal']))
        for table in table_results['table_issues'][:3]:
            content.append(Paragraph(f"Table #{table['table_number']}:", styles['Normal']))
            for issue in table['issues'][:3]:  # Limit to first 3 issues per table
                content.append(Paragraph(f"• {issue}", styles['Normal']))
    
    content.append(Spacer(1, 0.3*inch))
    
    # Key Recommendations
    content.append(Paragraph("Key Recommendations", styles['Heading1']))
    
    recommendations = []
    
    # Generate recommendations based on issues found
    if results['img_alt_text']['missing_alt']:
        recommendations.append("Add alt text to all images that convey information.")
    
    if "No H1 heading found" in str(results['heading_structure']['issues']):
        recommendations.append("Add a single H1 heading to the page that describes its main purpose.")
    
    if "Heading level skip" in str(results['heading_structure']['issues']):
        recommendations.append("Fix heading structure to avoid skipping levels (e.g., don't go from H1 to H3 without H2).")
    
    if results['form_accessibility']['forms_with_issues'] > 0:
        recommendations.append("Add proper labels to all form inputs.")
    
    if not results['language']['language_specified']:
        recommendations.append("Add the lang attribute to the HTML element (e.g., `<html lang=\"en\">`).")
    
    landmark_issues = results['landmarks_aria']['issues']
    if landmark_issues:
        for issue in landmark_issues:
            if "main content" in issue:
                recommendations.append("Add a main landmark (using <main> element or role=\"main\") to identify the main content area.")
            if "navigation landmark" in issue:
                recommendations.append("Add a navigation landmark (using <nav> element or role=\"navigation\") to identify navigation areas.")
    
    if results['keyboard_accessibility']['keyboard_issues']:
        recommendations.append("Ensure all interactive elements are keyboard accessible.")
    
    if results['links']['links_with_issues'] > 0:
        recommendations.append("Use descriptive link text instead of generic phrases like 'click here' or 'read more'.")
        if any("new window" in issue['issue'] for issue in results['links']['link_issues']):
            recommendations.append("Add warnings when links open in new windows or tabs.")
    
    # Display recommendations (up to 5)
    for i, recommendation in enumerate(recommendations[:5], 1):
        content.append(Paragraph(f"{i}. {recommendation}", styles['Normal']))
    
    content.append(Spacer(1, 0.3*inch))
    
    # Resources
    content.append(Paragraph("Resources for Improving Accessibility", styles['Heading1']))
    content.append(Paragraph("• Web Content Accessibility Guidelines (WCAG): www.w3.org/WAI/standards-guidelines/wcag/", styles['Normal']))
    content.append(Paragraph("• WebAIM: Web Accessibility In Mind: webaim.org", styles['Normal']))
    content.append(Paragraph("• The A11Y Project: www.a11yproject.com", styles['Normal']))
    content.append(Paragraph("• MDN Web Docs: Accessibility: developer.mozilla.org/en-US/docs/Web/Accessibility", styles['Normal']))
    
    # Build the PDF
    doc.build(content)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    
    return pdf_bytes

def get_download_link(pdf_bytes, filename="accessibility_report.pdf"):
    """Generate a download link for the PDF."""
    b64 = base64.b64encode(pdf_bytes).decode()
    href = f'<a href="data:application/octet-stream;base64,{b64}" download="{filename}">Download PDF Report</a>'
    return href

def main():
    st.title("Web Accessibility Analyzer")
    st.markdown(
        """
        This tool analyzes websites for barrier-free access (accessibility). Enter a URL to scan for common 
        accessibility issues that might affect users with disabilities.
        """
    )
    
    url = st.text_input("Enter a website URL to analyze:", "https://example.com")
    
    if st.button("Analyze Website") and url:
        if not is_valid_url(url):
            st.error("Please enter a valid URL (including http:// or https://).")
            return
        
        with st.spinner("Analyzing website accessibility... This may take a moment."):
            results = analyze_accessibility(url)
            
        if results:
            # Calculate the accessibility score
            score_results = calculate_score(results)
            score = score_results['score']
            
            # Create PDF report
            pdf_bytes = create_pdf_report(results, score_results)
            
            # Display download button for PDF
            st.download_button(
                label="Download PDF Report",
                data=pdf_bytes,
                file_name=f"accessibility_report_{url.replace('https://', '').replace('http://', '').replace('/', '_')}.pdf",
                mime="application/pdf"
            )
            
            # Display the score
            st.markdown("## Accessibility Score")
            st.markdown(
                f"<h1 style='text-align: center; color: {get_score_color(score)};'>{score}/100</h1>", 
                unsafe_allow_html=True
            )
            
            if score_results['deductions']:
                st.markdown("### Score Deductions")
                for deduction in score_results['deductions']:
                    st.markdown(f"- {deduction}")
            
            # Display accessibility summary
            st.markdown("## Accessibility Summary")
            
            col1, col2 = st.columns(2)
            
            # Column 1
            with col1:
                st.markdown("### Images")
                if results['img_alt_text']['total_images'] > 0:
                    alt_percentage = (results['img_alt_text']['images_with_alt'] / results['img_alt_text']['total_images']) * 100
                    st.markdown(f"- Total images: {results['img_alt_text']['total_images']}")
                    st.markdown(f"- Images with alt text: {results['img_alt_text']['images_with_alt']} ({alt_percentage:.1f}%)")
                    if results['img_alt_text']['missing_alt']:
                        with st.expander("Images missing alt text"):
                            for src in results['img_alt_text']['missing_alt'][:10]:  # Show only the first 10
                                st.markdown(f"- `{src[:100]}...`" if len(src) > 100 else f"- `{src}`")
                            if len(results['img_alt_text']['missing_alt']) > 10:
                                st.markdown(f"... and {len(results['img_alt_text']['missing_alt']) - 10} more")
                else:
                    st.markdown("- No images found on the page.")
                
                st.markdown("### Headings")
                headings = results['heading_structure']
                for level, count in headings['heading_levels'].items():
                    st.markdown(f"- {level.upper()}: {count}")
                
                if headings['issues']:
                    with st.expander("Heading structure issues"):
                        for issue in headings['issues']:
                            st.markdown(f"- {issue}")
                
                st.markdown("### Language")
                lang_results = results['language']
                if lang_results['language_specified']:
                    st.markdown(f"- Language specified: {lang_results['language']}")
                else:
                    st.markdown("- ❌ Language not specified. The `lang` attribute should be added to the HTML element.")
            
            # Column 2
            with col2:
                st.markdown("### Landmarks & ARIA")
                for landmark, count in results['landmarks_aria']['landmarks'].items():
                    st.markdown(f"- {landmark}: {count}")
                
                if results['landmarks_aria']['issues']:
                    with st.expander("Landmark issues"):
                        for issue in results['landmarks_aria']['issues']:
                            st.markdown(f"- {issue}")
                
                st.markdown("### Forms")
                form_results = results['form_accessibility']
                st.markdown(f"- Total forms: {form_results['total_forms']}")
                st.markdown(f"- Forms with issues: {form_results['forms_with_issues']}")
                
                if form_results['forms_with_issues'] > 0:
                    with st.expander("Form accessibility issues"):
                        for form in form_results['form_issues']:
                            st.markdown(f"**Form #{form['form_number']}**")
                            for issue in form['issues']:
                                st.markdown(f"- {issue}")
                
                st.markdown("### Links")
                link_results = results['links']
                st.markdown(f"- Total links: {link_results['total_links']}")
                st.markdown(f"- Links with issues: {link_results['links_with_issues']}")
                
                if link_results['links_with_issues'] > 0:
                    with st.expander("Link accessibility issues"):
                        for issue in link_results['link_issues']:
                            st.markdown(f"- {issue['issue']} (`{issue['url'][:50]}...`)" if len(issue['url']) > 50 else f"- {issue['issue']} (`{issue['url']}`)")
            
            # Detailed results
            with st.expander("Keyboard Accessibility"):
                keyboard_results = results['keyboard_accessibility']
                st.markdown(f"- Elements with onclick handlers: {keyboard_results['onclick_elements']}")
                st.markdown(f"- Elements with problematic tabindex: {keyboard_results['problematic_tabindex']}")
                
                if keyboard_results['keyboard_issues']:
                    st.markdown("**Issues:**")
                    for issue in keyboard_results['keyboard_issues']:
                        st.markdown(f"- {issue}")
            
            with st.expander("Table Accessibility"):
                table_results = results['tables']
                st.markdown(f"- Total tables: {table_results['total_tables']}")
                st.markdown(f"- Tables with issues: {table_results['tables_with_issues']}")
                
                if table_results['tables_with_issues'] > 0:
                    st.markdown("**Issues:**")
                    for table in table_results['table_issues']:
                        st.markdown(f"**Table #{table['table_number']}**")
                        for issue in table['issues']:
                            st.markdown(f"- {issue}")
            
            with st.expander("Color Information (Potential Contrast Issues)"):
                st.markdown("""
                **Note:** This is only a preliminary check. Full color contrast analysis requires rendering 
                the page and checking actual colors, which is beyond the scope of this tool.
                """)
                
                color_results = results['color_contrast']
                if color_results['color_properties']:
                    st.markdown("**Inline Color Properties:**")
                    for prop in color_results['color_properties']:
                        st.markdown(f"- {prop}")
                
                if color_results['common_classes']:
                    st.markdown("**Most Common CSS Classes:**")
                    for cls, count in color_results['common_classes'].items():
                        st.markdown(f"- `.{cls}`: {count} occurrences")
            
            # Recommendations
            st.markdown("## Key Recommendations")
            recommendations = []
            
            # Add recommendations based on issues found
            if results['img_alt_text']['missing_alt']:
                recommendations.append("Add alt text to all images that convey information.")
            
            if "No H1 heading found" in str(results['heading_structure']['issues']):
                recommendations.append("Add a single H1 heading to the page that describes its main purpose.")
            
            if "Heading level skip" in str(results['heading_structure']['issues']):
                recommendations.append("Fix heading structure to avoid skipping levels (e.g., don't go from H1 to H3 without H2).")
            
            if results['form_accessibility']['forms_with_issues'] > 0:
                recommendations.append("Add proper labels to all form inputs.")
            
            if not results['language']['language_specified']:
                recommendations.append("Add the lang attribute to the HTML element (e.g., `<html lang=\"en\">`).")
            
            landmark_issues = results['landmarks_aria']['issues']
            if landmark_issues:
                for issue in landmark_issues:
                    if "main content" in issue:
                        recommendations.append("Add a main landmark (using <main> element or role=\"main\") to identify the main content area.")
                    if "navigation landmark" in issue:
                        recommendations.append("Add a navigation landmark (using <nav> element or role=\"navigation\") to identify navigation areas.")
            
            if results['keyboard_accessibility']['keyboard_issues']:
                recommendations.append("Ensure all interactive elements are keyboard accessible.")
            
            if results['links']['links_with_issues'] > 0:
                recommendations.append("Use descriptive link text instead of generic phrases like 'click here' or 'read more'.")
                if any("new window" in issue['issue'] for issue in results['links']['link_issues']):
                    recommendations.append("Add warnings when links open in new windows or tabs.")
            
            # Display recommendations
            for i, recommendation in enumerate(recommendations[:5], 1):
                st.markdown(f"{i}. {recommendation}")
            
            # Resources
            st.markdown("## Resources for Improving Accessibility")
            st.markdown("""
            - [Web Content Accessibility Guidelines (WCAG)](https://www.w3.org/WAI/standards-guidelines/wcag/)
            - [WebAIM: Web Accessibility In Mind](https://webaim.org/)
            - [The A11Y Project](https://www.a11yproject.com/)
            - [MDN Web Docs: Accessibility](https://developer.mozilla.org/en-US/docs/Web/Accessibility)
            """)
        else:
            st.error("Unable to analyze the website. Please check the URL and try again.")


if __name__ == "__main__":
    main()
