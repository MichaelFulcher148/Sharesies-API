import requests
from sharesies.util import PropagatingThread
from queue import Queue
import math


class Client:

    def __init__(self):
        # session to remain logged in
        self.session = requests.Session()
        self.session.headers = {
            "User-Agent": "Mozilla/5.0 Firefox/71.0",
            "Accept": "*/*",
            "content-type": "application/json",
        }

        self.user_id = ""
        self.password = ""
        self.auth_token = ""
        self.rakaia_token = ""

    def login(self, email, password):
        '''
        You must login first to access certain features
        '''

        login_form = {
            'email': email,
            'password': password,
            'remember': True
        }

        resp = self.session.post(
            'https://app.sharesies.nz/api/identity/login',
            json=login_form
        )

        r = resp.json()

        if r['authenticated']:
            self.user_id = r['user_list'][0]['id']
            self.password = password  # Used for reauth
            self.auth_token = r['distill_token']
            self.rakaia_token = r['rakaia_token']
            self.session_cookie = resp.cookies['session']
            return True

        return False
    
    def logout(self):
        '''
        Clears the login session data
        '''

        self.user_id = None
        self.password = None
        self.auth_token = None
        self.session_cookie = None

    def get_transactions(self, since=0):
        '''
        Get all transactions in wallet since a certain transaction_id
        (0 is all-time)
        '''

        transactions = []

        cookies = {
            'session': self.session_cookie
        }

        params = {
            'limit': 50,
            'acting_as_id': self.user_id,
            'since': since
        }

        has_more = True
        while has_more:
            r = self.session.get(
                "https://app.sharesies.nz/api/accounting/transaction-history",
                params=params, cookies=cookies)
            response = r.json()
            transactions.extend(response['transactions'])
            has_more = response['has_more']
            params['before'] = transactions[-1]['transaction_id']

        return transactions

    def get_shares(self, managed_funds=False):
        '''
        Get all shares listed on Sharesies
        '''

        shares = []

        page = self.get_instruments(1, managed_funds)
        number_of_pages = page['numberOfPages']
        shares += page['instruments']

        threads = []
        que = Queue()

        # make threads
        for i in range(2, number_of_pages):
            threads.append(PropagatingThread(
                target=lambda q,
                arg1: q.put(self.get_instruments(arg1, managed_funds)),
                args=(que, i)))

        # start threads
        for thread in threads:
            thread.start()

        # join threads
        for thread in threads:
            thread.join()

        while not que.empty():
            shares += que.get()['instruments']

        return shares

    def get_instruments(self, page, managed_funds=False):
        '''
        Get a certain page of shares
        '''

        headers = self.session.headers
        headers['Authorization'] = f'Bearer {self.auth_token}'

        params = {
            'Page': page,
            'Sort': 'marketCap',
            'PriceChangeTime': '1y',
            'Query': ''
        }

        if managed_funds:
            params['instrumentTypes'] = ['mf']

        r = self.session.get("https://data.sharesies.nz/api/v1/instruments",
                             params=params, headers=headers)
        response = r.json()

        # get dividends and price history
        for i in range(len(response['instruments'])):
            current = response['instruments'][i]
            id_ = current['id']
            # current['dividends'] = self.get_dividends(id_)
            current['priceHistory'] = self.get_price_history(id_)

        return response
    
    def get_weekly_top_ten(self, index=None):
        '''
        Get the weekly top ten funds.
        If index is None, returns all fund IDs.
        Otherwise, returns the fund ID at the specified index.
        '''

        if index is not None and (index < 0 or index >= 10):
            raise IndexError("Index out of range. Please provide an index between 0 and 10")

        r = self.session.get(
            'https://app.sharesies.nz/api/explore/weekly-top-ten-funds',
        )
        
        response = r.json()
        fund_ids = response['fund_ids']

        if index is not None:
            return fund_ids[index]

        return fund_ids  # Return all fund IDs if index is None

    def get_instrument(self, fund_id):
        '''
        Get a certain share
        '''
        
        headers = self.session.headers
        headers['Authorization'] = f'Bearer {self.auth_token}'

        r = self.session.get(
            f'https://data.sharesies.nz/api/v1/instruments/{fund_id}',
            headers=headers)
        
        response = r.json()

        # get dividends and price history
        # response['dividends'] = self.get_dividends(fund_id)
        response['priceHistory'] = self.get_price_history(fund_id)

        return response

    def get_dividends(self, share_id):
        '''
        Get certain stocks dividends
        '''

        headers = self.session.headers
        headers['Authorization'] = f'Bearer {self.auth_token}'

        r = self.session.get(
            "https://data.sharesies.nz/api/v1/instruments/"
            f"{share_id}/dividends")

        # TODO: Clean up output
        return r.json()['dividends']

    def get_price_history(self, share_id):
        '''
        Get certain stocks price history
        '''

        headers = self.session.headers
        headers['Authorization'] = f'Bearer {self.auth_token}'

        r = self.session.get(
            "https://data.sharesies.nz/api/v1/instruments/"
            f"{share_id}/pricehistory")

        return r.json()['dayPrices']

    def get_companies(self, page=1):
        '''
        Gets a certain page of companies
        '''

        headers = self.session.headers
        headers['Authorization'] = f'Bearer {self.auth_token}'

        r = self.session.get(
            'https://data.sharesies.nz/api/v1/instruments?Page='+str(page)+'&PerPage=500&Sort=marketCap&PriceChangeTime=1y&Query='
        )

        companies = [item for item in r.json()["instruments"] if item["instrumentType"] == "equity"]

        return companies

    def get_info(self):
        '''
        Get basic market info
        '''
        headers = self.session.headers
        headers['Authorization'] = f'Bearer {self.auth_token}'

        r = self.session.get(
            "https://data.sharesies.nz/api/v1/instruments/info")
        return r.text

    def get_profile(self):
        '''
        Returns the logged in user's profile
        '''

        r = self.session.get(
            'https://app.sharesies.nz/api/identity/check'
        )

        return r.json()
    
    def get_wallet_balance(self):
        '''
        Returns the logged in user's wallet balance
        '''

        r = self.session.get(
            'https://app.sharesies.nz/api/identity/check'
        )

        response = r.json()
        wallet = response['user']['wallet_balances']

        return wallet
    
    def transfer_funds(self, source_currency, target_currency, source_amount):
        '''
        Transfers currency between the currencies specified
        '''

        self.reauth()  # Avoid timeout

        headers = self.session.headers
        headers['Authorization'] = f'Bearer {self.auth_token}'

        exchange_r = self.session.get(
            f'https://app.sharesies.nz/api/fx/get-rate-v2?acting_as_id={self.user_id}'
        )

        rate_data = exchange_r.json()

        exchange_rate = None

        # Loop through the response of currency pairs and find the correct one based on params
        for currency in rate_data['fx_currencies']:
            if (currency['source_currency'] == source_currency and 
                    currency['target_currency'] == target_currency):
                exchange_rate = float(currency['rate'])
                break

        if exchange_rate is None:
            raise ValueError(f"No exchange rate found for {source_currency} to {target_currency}")
        
        # calculate fee
        source_fee = source_amount * 0.004975

        # calculate target amount and round as sharesies api expects
        target_amount = (source_amount - source_fee) * exchange_rate
        target_amount = math.floor(target_amount * 100) / 100

        if target_amount < 0.01:
            raise ValueError("Your source currency amount does not equal at least 0.01 of the target currency")

        transfer_info = {
            'acting_as_id': self.user_id,
            'source_currency': source_currency,
            'target_currency': target_currency,
            'quoted_rate': exchange_rate,
            'source_amount': source_amount,
            'target_amount': target_amount,
            'source_fee': source_fee,
            'buy_or_sell': 'sell'
        }

        r = self.session.post(
            f'https://app.sharesies.nz/api/fx/create-order',
            json=transfer_info
        )

        return r.json()

    def get_portfolio(self, portfolio_id):
        '''
        Returns the portfolio of a user
        '''

        headers = self.session.headers
        headers['Authorization'] = f'Bearer {self.rakaia_token}'

        r = self.session.get(
            f'https://portfolio.sharesies.nz/api/v1/portfolios/{portfolio_id}'
        )

        return r.json()

    def get_order_history(self, fund_id):
        '''
        Returns your order history for a given fund.
        '''

        self.reauth()  # Avoid timeout

        r = self.session.get(
            'https://app.sharesies.nz/api/accounting/order-history-v4' +
            '?fund_id=' + fund_id + '&acting_as_id=' + self.user_id
        )

        return r.json()['orders']

    def buy(self, company, amount):
        '''
        Purchase stocks from the NZX Market
        '''

        self.reauth()  # avoid timeout

        buy_info = {
            'action': 'place',
            'amount': amount,
            'fund_id': company['id'],
            'expected_fee': amount*0.005,
            'acting_as_id': self.user_id
        }

        r = self.session.post(
            'https://app.sharesies.nz/api/cart/immediate-buy-v2',
            json=buy_info
        )

        return r.status_code == 200
    
    def auto_invest_create(self, amount, interval, start, companies, percentages, order_name):
        '''
        Create an auto invest order
        '''
        
        self.reauth() # Avoid timeout
        
        allocations = [{"fund_id": company['id'], "allocation": str(percentage)} for company, percentage in zip(companies, percentages)]
        
        auto_invest_info = {
            'acting_as_id': self.user_id,
            'amount': amount,
            'interval': interval,
            'start': start,
            'allocations': allocations,
            'order_name': order_name,   
        }
        
        r = self.session.post(
            'https://app.sharesies.nz/api/autoinvest/set-diy-order',
            json=auto_invest_info
        )
        
        return r.status_code == 200
    
    def auto_invest_update(self, order_id, amount, interval, start, companies, percentages, order_name):
        '''
        Update an existing auto invest order
        '''
        
        self.reauth() # Avoid timeout
        
        allocations = [{"fund_id": company['id'], "allocation": str(percentage)} for company, percentage in zip(companies, percentages)]
        
        auto_invest_info = {
            'acting_as_id': self.user_id,
            'amount': amount,
            'interval': interval,
            'order_id': order_id,
            'start': start,
            'allocations': allocations,
            'order_name': order_name,   
        }
        
        r = self.session.post(
            'https://app.sharesies.nz/api/autoinvest/set-diy-order',
            json=auto_invest_info
        )
        
        return r.status_code == 200

    def sell(self, company, shares):
        '''
        Sell shares from the NZX Market
        '''

        self.reauth()  # Avoid timeout

        sell_info = {
            'shares': shares,
            'fund_id': company['fund_id'],
            'acting_as_id': self.user_id,
        }

        r = self.session.post(
            'https://app.sharesies.nz/api/fund/sell',
            json=sell_info
        )

        return r.status_code == 200

    def reauth(self):
        '''
        Reauthenticates user on server
        '''

        creds = {
            "password": self.password,
            "acting_as_id": self.user_id
        }

        r = self.session.post(
            'https://app.sharesies.nz/api/identity/reauthenticate',
            json=creds
        )

        return r.status_code == 200
