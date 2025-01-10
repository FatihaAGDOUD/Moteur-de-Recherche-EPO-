import requests
import xml.etree.ElementTree as ET
from flask import Flask, render_template, request, flash
from concurrent.futures import ThreadPoolExecutor
from getToken import get_token_manager
import time
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry # type: ignore

app = Flask(__name__)
app.secret_key = '9QTRKvF0q3eyptZxyiv3WZEZvTMHWz2XODmpKhWKrnZ5nEcB7cOSe7O8zKvbxPgE'
app.jinja_env.globals.update(max=max, min=min)

def get_current_token():
    token_manager = get_token_manager()
    return token_manager.get_valid_token()

def create_retry_session(retries=3, backoff_factor=0.3):
    """Create a requests session with retry functionality"""
    session = requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

def get_patent_details(patent_info):
    """Fetch additional patent details including title, inventors and CIB classifications"""
    doc_number = patent_info['doc_number'].strip().replace(" ", "")
    country = patent_info['country']
    kind = patent_info['kind']
    
    url_formats = [
        f"https://ops.epo.org/3.2/rest-services/published-data/publication/epodoc/{country}.{doc_number}.{kind}/biblio",
        f"https://ops.epo.org/3.2/rest-services/published-data/publication/docdb/{country}.{doc_number}.{kind}/biblio",
        f"https://ops.epo.org/3.2/rest-services/published-data/publication/original/{country}.{doc_number}.{kind}/biblio"
    ]
    
    headers = {
        'Authorization': f'Bearer {get_current_token()}',
        'Accept': 'application/xml'
    }
    
    session = create_retry_session()
    last_error = None
    
    for url in url_formats:
        try:
            time.sleep(0.1)
            
            response = session.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            if not response.text.strip():
                continue
                
            root = ET.fromstring(response.text)
            
            namespaces = {
                'ops': 'http://ops.epo.org',
                'exchange': 'http://www.epo.org/exchange',
                'xmlns': 'http://www.epo.org/exchange'
            }
            
            # Get title
            title = None
            title_paths = [
                './/exchange:invention-title[@lang="en"]',
                './/xmlns:invention-title[@lang="en"]',
                './/exchange:invention-title',
                './/xmlns:invention-title'
            ]
            
            for path in title_paths:
                try:
                    title_elems = root.findall(path, namespaces)
                    for title_elem in title_elems:
                        if title_elem is not None and title_elem.text:
                            if title_elem.get('lang') == 'en':
                                title = title_elem.text.strip()
                                break
                            elif not title:
                                title = title_elem.text.strip()
                    if title:
                        break
                except ET.ParseError:
                    continue

            # Get CIB classifications
            classifications = []
            classification_paths = [
                './/exchange:classifications-ipcr/exchange:classification-ipcr',
                './/xmlns:classifications-ipcr/xmlns:classification-ipcr',
                './/exchange:classification-ipc',
                './/xmlns:classification-ipc'
            ]
            
            for path in classification_paths:
                try:
                    for classification in root.findall(path, namespaces):
                        # Try different XML structures for IPC/CPC
                        text_elem = (classification.find('.//exchange:text', namespaces) or 
                                   classification.find('.//xmlns:text', namespaces))
                        
                        if text_elem is not None and text_elem.text:
                            classifications.append(text_elem.text.strip())
                        else:
                            # Alternative structure: concatenate section, class, subclass, etc.
                            parts = []
                            for part in ['section', 'class', 'subclass', 'main-group', 'subgroup']:
                                elem = (classification.find(f'.//exchange:{part}', namespaces) or 
                                      classification.find(f'.//xmlns:{part}', namespaces))
                                if elem is not None and elem.text:
                                    parts.append(elem.text.strip())
                            if parts:
                                classifications.append(''.join(parts))
                except ET.ParseError:
                    continue
                    
            # Get inventors
            inventors = []
            inventor_paths = [
                './/exchange:inventor/exchange:name',
                './/xmlns:inventor/xmlns:name'
            ]
            
            for path in inventor_paths:
                try:
                    for inventor in root.findall(path, namespaces):
                        firstname = inventor.find('.//exchange:firstname', namespaces) or inventor.find('.//xmlns:firstname', namespaces)
                        lastname = inventor.find('.//exchange:lastname', namespaces) or inventor.find('.//xmlns:lastname', namespaces)
                        
                        name_parts = []
                        if firstname is not None and firstname.text:
                            name_parts.append(firstname.text.strip())
                        if lastname is not None and lastname.text:
                            name_parts.append(lastname.text.strip())
                        
                        if name_parts:
                            inventors.append(" ".join(name_parts))
                except ET.ParseError:
                    continue
                
            if title:
                patent_info.update({
                    'title': title,
                    'inventors': inventors,
                    'classifications': classifications,
                    'error': None
                })
                return patent_info
                
        except requests.exceptions.RequestException as e:
            last_error = e
            continue
            
    if isinstance(last_error, requests.exceptions.Timeout):
        patent_info.update({
            'title': "Request timed out - please try again",
            'inventors': [],
            'classifications': [],
            'error': 'timeout'
        })
    elif isinstance(last_error, requests.exceptions.RequestException):
        if hasattr(last_error.response, 'status_code') and last_error.response.status_code == 429:
            patent_info.update({
                'title': "Rate limit exceeded - please try again later",
                'inventors': [],
                'classifications': [],
                'error': 'rate_limit'
            })
        else:
            try:
                espacenet_url = f"https://worldwide.espacenet.com/patent/search?q={country}{doc_number}{kind}"
                response = session.get(espacenet_url, timeout=15)
                if response.status_code == 200:
                    patent_info.update({
                        'title': "Title available on Espacenet",
                        'inventors': [],
                        'classifications': [],
                        'error': None,
                        'espacenet_url': espacenet_url
                    })
                else:
                    patent_info.update({
                        'title': "Temporarily unavailable - please try again",
                        'inventors': [],
                        'classifications': [],
                        'error': 'network'
                    })
            except:
                patent_info.update({
                    'title': "Temporarily unavailable - please try again",
                    'inventors': [],
                    'classifications': [],
                    'error': 'network'
                })
    else:
        patent_info.update({
            'title': "Error retrieving patent information",
            'inventors': [],
            'classifications': [],
            'error': 'unknown'
        })
    
    return patent_info

def search_patents(query, range_start=1, range_end=25):
    url = "https://ops.epo.org/3.2/rest-services/published-data/search"
    
    params = {
        'q': query,
        'Range': f"{range_start}-{range_end}"
    }
    
    headers = {
        'Authorization': f'Bearer {get_current_token()}',
        'Accept': 'application/xml'
    }
    
    try:
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        return parse_patent_xml(response.text)
    except requests.exceptions.RequestException as e:
        flash(f"Error while fetching patent data: {e}", "error")
        return None

def parse_patent_xml(xml_data):
    root = ET.fromstring(xml_data)
    
    namespaces = {
        'ops': 'http://ops.epo.org',
        '': 'http://www.epo.org/exchange'
    }

    total_results = root.find('.//ops:biblio-search', namespaces).get('total-result-count')
    
    patents = []
    for patent in root.findall('.//ops:publication-reference', namespaces):
        family_id = patent.get('family-id')
        country = patent.find('.//country', namespaces).text
        doc_number = patent.find('.//doc-number', namespaces).text
        kind = patent.find('.//kind', namespaces).text
        
        patents.append({
            'family_id': family_id,
            'country': country,
            'doc_number': doc_number,
            'kind': kind,
            'espacenet_url': f"https://worldwide.espacenet.com/patent/search?q={country}{doc_number}{kind}"
        })
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        patents = list(executor.map(get_patent_details, patents))
    
    return {'patents': patents, 'total_results': total_results}

@app.route('/', methods=['GET', 'POST'])
def home():
    query = request.args.get('query', '')
    page = int(request.args.get('page', 1))
    per_page = 25
    
    if query:
        range_start = (page - 1) * per_page + 1
        range_end = range_start + per_page - 1
        result = search_patents(query, range_start, range_end)
        if result:
            total_results = int(result['total_results'])
            total_pages = (total_results + per_page - 1) // per_page
            return render_template('index.html', 
                                patents=result['patents'], 
                                query=query,
                                current_page=page,
                                total_pages=total_pages,
                                total_results=total_results)
    
    return render_template('index.html', patents=None, query=query)

if __name__ == '__main__':
    app.run(debug=True)