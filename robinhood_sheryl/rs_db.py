# sqlalchemy imports
from sqlalchemy import Column, Float, BigInteger, Boolean, DateTime, Text, Date
from sqlalchemy.ext.declarative import declarative_base
# from sqlalchemy.orm import relationship, sessionmaker

from robinhood_sheryl.pg_connection import *

# postgres imports
from sqlalchemy.dialects.postgresql import insert

# data analysis imports
import pandas as pd
import numpy as np

# time imports
import time
from datetime import datetime, timedelta
import pytz
import pendulum
from pandas.tseries.offsets import BDay  # Business day

# yfinance imports
import yfinance as yf

# robinhood imports
import robin_stocks as r
from robinhood_sheryl.login import login

# system imports
import logging
import os
import io
import tempfile

#### logging setup
logging.basicConfig(level=logging.DEBUG, format=' %(asctime)s - %(levelname)s - %(message)s: %(lineno)d')
date_time = ' %(asctime)s - %(levelname)s - %(message)s'
logging.debug('Start of program')
logger = logging.getLogger()
# logger.disabled = True

# #### set timezone
local_tz = pendulum.timezone("US/Eastern")

def get_UTC_datetime_now():
    return datetime.now(tz=pytz.timezone('UTC')).replace(microsecond=0)


def convert_datetime(x, timezone='UTC'):
    utc = pytz.utc
    eastern = pytz.timezone('US/Eastern')
    if timezone == 'UTC':
        date_eastern = eastern.localize(x, is_dst=None)
        return date_eastern.astimezone(utc)
    else: # timezone == 'EST'
        return x.astimezone(utc)


#### global variables

DATABASE = 'prod'
# TICKERS_PART = None
DIR_PATH = os.path.dirname(os.path.realpath(__file__))
INDEXES = {'Nasdaq': '^IXIC',
           'SP': '^GSPC',
           'Dow': '^DJI',
           'Vix': '^VIX',
           'Russel': '^RUT',
           'FTSE': '^FTSE',
           'Nikkei': '^N225'}

##################
# DATABASE
##################

conn = init_connection_engine()
Base = declarative_base()
# meta = MetaData(conn).reflect()


#### define tables

class equitiesTable(Base):
    __tablename__ = 'equities'

    datetime = Column(DateTime(timezone=True), primary_key=True)
    ticker = Column(Text, primary_key=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(BigInteger)
    dividends = Column(Float)
    stock_splits = Column(BigInteger)


class tickersTable(Base):
    __tablename__ = 'tickers'

    ticker = Column(Text, primary_key=True)
    t_type = Column(Text, primary_key=True)
    id = Column(Text, primary_key=True)
    name = Column(Text)
    hold = Column(Boolean)


class portfolioTable(Base):
    __tablename__ = 'portfolio'

    datetime = Column(DateTime(timezone=True), primary_key=True, default=get_UTC_datetime_now())
    ticker = Column(Text, primary_key=True)
    average_buy_price = Column(Float)
    quantity = Column(Float)
    prev_close_price = Column(Float)
    prev_close_unadjusted = Column(Float)
    latest_price = Column(Float)
    ask_price = Column(Float)
    ask_size = Column(BigInteger)
    bid_price = Column(Float)
    bid_size = Column(BigInteger)
    last_trade_price = Column(Float)
    last_extended_hours_trade_price = Column(Float)
    previous_close_date = Column(Date)


class cryptoTable(Base):
    __tablename__ = 'crypto'

    datetime = Column(DateTime(timezone=True), primary_key=True, default=get_UTC_datetime_now())
    name = Column(Text, primary_key=True)
    ticker = Column(Text)
    average_buy_price = Column(Float)
    quantity = Column(Float)
    prev_close_price = Column(Float)
    latest_price = Column(Float)


class optionsTable(Base):
    __tablename__ = 'options'

    datetime = Column(DateTime(timezone=True), primary_key=True, default=get_UTC_datetime_now())
    option_id = Column(Text, primary_key=True)
    ticker = Column(Text)
    option_type = Column(Text)
    exp_date = Column(Date)
    strike_price = Column(Float)
    quantity = Column(Float)
    average_buy_price = Column(Float)
    latest_price = Column(Float)
    prev_close_price = Column(Float)
    break_even_price = Column(Float)
    ask_price = Column(Float)
    ask_size = Column(Float)
    bid_price = Column(Float)
    bid_size = Column(Float)
    high_price = Column(Float)
    last_trade_price = Column(Float)
    last_trade_size = Column(Float)
    low_price = Column(Float)
    open_interest = Column(Float)
    volume = Column(Float)
    chance_of_profit_long = Column(Float)
    chance_of_profit_short = Column(Float)
    delta = Column(Float)
    gamma = Column(Float)
    implied_volatility = Column(Float)
    rho = Column(Float)
    theta = Column(Float)
    vega = Column(Float)
    previous_close_date = Column(Date)


class portfolioSummaryTable(Base):
    __tablename__ = 'portfolio_summary'

    datetime = Column(DateTime(timezone=True), primary_key=True, default=get_UTC_datetime_now())
    username = Column(Text, primary_key=True)
    crypto_equity = Column(Float)
    crypto_equity_prev_close = Column(Float)
    equity_latest = Column(Float)
    equity_prev_close = Column(Float)
    withdrawable_amount = Column(Float)
    excess_margin = Column(Float)
    excess_maintenance = Column(Float)


def initTables():
    isRun = False
    Base.metadata.create_all(bind=conn)
    print(Base.metadata.sorted_tables)
    isRun = True
    return isRun


#### read sql fast
def read_sql_inmem_uncompressed(query, db_engine):
    copy_sql = "COPY ({query}) TO STDOUT WITH CSV {head}".format(
        query=query, head="HEADER"
    )
    try:
        raw_conn = db_engine.raw_connection()
        cur = raw_conn.cursor()
        store = io.StringIO()
        cur.copy_expert(copy_sql, store)
        store.seek(0)
        df = pd.read_csv(store)
        cur.close()
        raw_conn.close()
        return df
    except Exception as e:
        print(f'==============\nException: {e}\n==============')
        return False


def read_sql_tmpfile(query, db_engine):
    try:
        with tempfile.TemporaryFile() as tmpfile:
            copy_sql = "COPY ({query}) TO STDOUT WITH CSV {head}".format(
               query=query, head="HEADER"
            )
            raw_conn = db_engine.raw_connection()
            cur = raw_conn.cursor()
            cur.copy_expert(copy_sql, tmpfile)
            tmpfile.seek(0)
            df = pd.read_csv(tmpfile)
            cur.close()
            raw_conn.close()
            return df
    except Exception as e:
        print(f'==============\nException: {e}\n==============')
        return False


#### execute sql query

def executeQuery(query):
    logging.debug(query)
    try:
        # dwhConnection = conn.connect()
        # df = pd.read_sql(query, con=dwhConnection)
        df = read_sql_inmem_uncompressed(query, conn)
        # df = read_sql_tmpfile(query, conn)
        # columns from cloud sql are byte form
        if isinstance(df.columns[0], bytes):
            df.columns = [c.decode() for c in df.columns]
        if not df.empty:
            if 'datetime' in df.columns:
                df['datetime'] = pd.to_datetime(df['datetime'])
                if df['datetime'].iloc[0].tzinfo is None:  # not tz aware, used in yf analysis functions
                    df['datetime'] = df['datetime'].dt.tz_localize('UTC').dt.tz_convert('US/Eastern')
                else: # already tz aware, downloaded data from yf
                    df['datetime'] = df['datetime'].dt.tz_convert('US/Eastern')
        # dwhConnection.close()
        return df
    except Exception as e:
        print(f'==============\nException at executeQuery: {e}\n==============')
        return False


#### get column data

def getColumns(table):
    df = executeQuery(f"SELECT column_name FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = '{table.__tablename__}';")
    return df['column_name'].to_list()


#### get data

def getData(table, rows={}, column='*', start_date='', end_date='',
            extended_hours=False,market_hours=('09:30','15:59:59'), timezone='US/Eastern'):
    has_datetime = table.__tablename__ in ['equities', 'portfolio', 'portfolio_summary']

    query = f" SELECT {column} FROM {table.__tablename__} WHERE TRUE "

    for k in rows:
        query += f" AND {k} = '{rows[k]}' "

    if has_datetime:
        if start_date:
            query += f" AND datetime AT TIME ZONE '{timezone}' >= '{start_date}'"
        if end_date:
            query += f" AND datetime AT TIME ZONE '{timezone}' <= '{end_date}'"
        if not extended_hours:
            query += f" AND (datetime AT TIME ZONE '{timezone}')::time BETWEEN '{market_hours[0]}' and '{market_hours[1]}' "
    try:
        df = executeQuery(query)
        if column != '*':
            ret_value = df[column]
            return ret_value if len(ret_value) == 1 else list(ret_value)  # if single value return the value
        if has_datetime:
            df['datetime'] = pd.to_datetime(df['datetime'])
            return df.set_index('datetime')
        else:
            return df
    except Exception as e:
        print(f'==============\nException at getData: {e}\n==============')
        return False


#### get latest row data

def getLatestRowData(table, value, key='ticker'):
    return executeQuery(
        f"SELECT * FROM {table.__tablename__} WHERE {key} = '{value}' AND datetime = (SELECT MAX(datetime) FROM {table.__tablename__} WHERE {key} = '{value}')")


#### get latest data


def getLatestData(table, key='ticker'):
    return executeQuery(
        f"SELECT * FROM {table.__tablename__} WHERE {key} NOT LIKE '^%%' AND (datetime,{key}) IN (SELECT MAX(datetime),{key} FROM {table.__tablename__} GROUP BY {key})")


#### get latest data with name

def getLatestDataNamed(table):
    return executeQuery(f"""
            SELECT t1.*, t2.name FROM
            (SELECT * FROM {table.__tablename__}
            WHERE (datetime,ticker) IN (SELECT MAX(datetime),ticker FROM {table.__tablename__} GROUP BY ticker)) t1
            JOIN (select distinct ticker, name from tickers) t2
            ON t1.ticker = t2.ticker
        """)


#### write data

def split_dataframe(df, chunk_size=2500):
    chunks = list()
    num_chunks = len(df) // chunk_size + 1
    for i in range(num_chunks):
        chunks.append(df[i * chunk_size:(i + 1) * chunk_size])
    return chunks


def insertData(table, df, db_name):
    try:
        dwhConnection = conn.connect()
        # cloud sql doesn't convert python datetime object properly
        if 'datetime' in df.columns:
            df['datetime'] = df['datetime'].dt.tz_convert('UTC').dt.strftime('%Y-%m-%d %H:%M:%S%z')
        chunks = split_dataframe(df)
        for chunk in chunks:
            pg_sql = insert(table.__table__, chunk.to_dict("records")).on_conflict_do_nothing()
            dwhConnection.execute(pg_sql)
        # print(pg_sql) # will give error 'The 'default' dialect with current database version settings does not support in-place multirow inserts.' bc print is not dialect aware
        print(f'==============\n{len(df)} rows written to {db_name} db {table.__tablename__} table in {len(chunks)} chunks\n==============')
        # logging.debug(f'{len(df)} rows written to {db_name} db {table.__tablename__} table in {len(chunks)} chunks')
        dwhConnection.close()
        return True
    except Exception as e:
        print(f'==============\nException at insertData: {e}\n==============')
        return False


#### update Tickers data
def updateData(table, df, db_name, index_elements):
    try:
        dwhConnection = conn.connect()
        if 'datetime' in df.columns:
            df['datetime'] = df['datetime'].dt.tz_convert('UTC').dt.strftime('%Y-%m-%d %H:%M:00%z')
        chunks = split_dataframe(df)
        for chunk in chunks:
            values = chunk.to_dict("records")
            stmt = insert(table.__table__).values(values)

            pg_sql = stmt.on_conflict_do_update(
                index_elements=index_elements,
                set_=dict(stmt.excluded)
            )
            dwhConnection.execute(pg_sql)
            # print(pg_sql) # will give error 'The 'default' dialect with current database version settings does not support in-place multirow inserts.' bc print is not dialect aware
        # logging.debug(f'{len(df)} rows updated/written to {db_name} db {table.__tablename__} table in {len(chunks)} chunks')
        print(
            f'==============\n{len(df)} rows updated/written to {db_name} db {table.__tablename__} table in {len(chunks)} chunks\n==============')
        dwhConnection.close()
        return True
    except Exception as e:
        print(f'==============\nException at updateData: {e}\n==============')
        return False

#### update yf Dividend data
def updateDividendsData(table, df, db_name, index_elements):
    try:
        dwhConnection = conn.connect()
        if 'datetime' in df.columns:
            df['datetime'] = df['datetime'].dt.tz_convert('UTC').dt.strftime('%Y-%m-%d %H:%M:00%z')
        chunks = split_dataframe(df)
        for chunk in chunks:
            values = chunk.to_dict("records")
            stmt = insert(table.__table__).values(values)

            pg_sql = stmt.on_conflict_do_update(
                index_elements=index_elements,
                set_=dict(dividends=stmt.excluded.dividends)
            )
            dwhConnection.execute(pg_sql)
            # print(pg_sql) # will give error 'The 'default' dialect with current database version settings does not support in-place multirow inserts.' bc print is not dialect aware
        # logging.debug(f'{len(df)} rows updated/written to {db_name} db {table.__tablename__} table in {len(chunks)} chunks')
        print(
            f'==============\n{len(df)} dividend rows updated to {db_name} db {table.__tablename__} table in {len(chunks)} chunks\n==============')
        dwhConnection.close()
        return True
    except Exception as e:
        print(f'==============\nException at updateDividendsData: {e}\n==============')
        return False


#### update Tickers data
def deleteRow(table, row, value, db_name):
    try:
        dwhConnection = conn.connect()
        pg_sql = f"""DELETE FROM {table.__tablename__}
                    WHERE {row} = '{value}' AND t_type='equity';"""

        # print(pg_sql) # will give error 'The 'default' dialect with current database version settings does not support in-place multirow inserts.' bc print is not dialect aware
        dwhConnection.execute(pg_sql)
        logging.debug(f'{value} deleted from {db_name} db {table.__tablename__} table')
        dwhConnection.close()
        return True
    except Exception as e:
        print(f'==============\nException at deleteRow: {e}\n==============')
        return False


##################
# YFINANCE
##################

#### get yfinance data and read tickers

def get_yf_data(ticker, start_date):
    stock = yf.Ticker(ticker)
    # df = stock.history(period='ytd', prepost=True)
    if start_date:
        df = stock.history(interval="1m", start=start_date, prepost=True)[:-1]  # drop duplicate data with non 0 seconds
    else:  # catchup
        df = stock.history(interval='1m', period='5d', prepost=True)[:-1]

    # logging.debug(f'getting data for {ticker}')
    if df.empty:
        logging.debug(f'{ticker}: No data found for this date range, symbol may be delisted')
        return df

    df = df.reset_index()
    df.insert(1, 'ticker', ticker)
    logging.debug(f"columns for {ticker} are: {','.join(df.columns)}")
    df.columns = ['datetime', 'ticker', 'open', 'high', 'low', 'close', 'volume', 'dividends', 'stock_splits']
    df['datetime'] = df['datetime'].dt.tz_convert('US/Eastern').dt.tz_convert('UTC')
    # df['datetime'] = df['datetime'].dt.tz_localize(None)
    return df


#### insert yfinance data

def insert_yf_data(tickers_list=None, catchup=False, print_details=False):
    if tickers_list is None:
        tickers_list = getData(tickersTable, column='ticker')
        tickers_list = list(set(tickers_list))
        tickers_list.extend(list(INDEXES.values()))
    if catchup is True:
        print(f"\n==============\nCATCHUP: getting data for equities for catchup run from period 5d\n==============")
    for ticker in tickers_list:
        # get max datetime of last ticker scrape
        start_time = getLatestRowData(equitiesTable, ticker)['datetime'].iloc[0]
        if pd.isnull(start_time) or catchup is True:  # no prior data, first time catchup run
            start_date = ''
            if print_details:
                print(f"\n==============\nREQUEST: getting data for equities {ticker} from period 5d\n==============")
        else:
            start_date = start_time.replace(tzinfo=None) - timedelta(minutes=5)
            if print_details:
                print(
                    f"\n==============\nREQUEST: getting data for equities {ticker} from {start_date}\n==============")
        df = get_yf_data(ticker, start_date)
        if df.empty:
            # no data for ticker, remove from ticker list
            # deleteRow(tickersTable,'ticker',ticker,DATABASE)
            print(f"\n==============\nSKIPPED: no data for {ticker}\n==============")
            status = True
        else:
            logging.debug(f'formatted data for {ticker}')
            df_dividends = df[df.isna().any(axis=1)]  # get dividends row if any
            if df_dividends.empty is False:
                df_dividends = df_dividends.fillna(0)
                status = updateDividendsData(equitiesTable, df_dividends, DATABASE, ['datetime', 'ticker'])
                if not status:
                    print(f"\n==============\nTERMINATED: Exception at {ticker} during update dividends\n==============")
                    return False
                df = df.dropna()  #drop na dividend rows
            status = insertData(equitiesTable, df, DATABASE)
            time.sleep(0.25)
        if not status:
            print(f"\n==============\nTERMINATED: Exception at {ticker} during insert\n==============")
            return False
    return True


##################
# PORTFOLIO
##################

#### update portfolio tickers

def update_portfolio_tickers(hold_ids, prev_hold_ids, t_type):
    logging.debug(f're-loading tickers for portfolio')
    # d = r.account.get_open_stock_positions()
    # df = pd.DataFrame.from_dict(d)
    current_tickers_df = getData(tickersTable, rows={'t_type': t_type})
    if isinstance(current_tickers_df,pd.DataFrame):
        current_tickers_df['hold'] = current_tickers_df['id'].apply(
            lambda x: True if x in hold_ids else False)
    else:
        current_tickers_df = pd.DataFrame()

    new_ids = np.setdiff1d(hold_ids, prev_hold_ids)
    print(f"\n==============\nNEW IDS TO INSERT:\n{new_ids}\n==============")

    tickers_df = pd.DataFrame()
    tickers_df['id'] = new_ids
    if t_type == 'option':
        tickers_df['ticker'] = tickers_df['id'].apply(
            lambda x: r.options.get_option_instrument_data_by_id(x, info='chain_symbol'))
    else:
        tickers_df['ticker'] = tickers_df['id'].apply(lambda x: r.stocks.get_stock_quote_by_id(x, info='symbol'))
        insert_yf_data(list(tickers_df['ticker']))

    tickers_df['name'] = tickers_df['ticker'].apply(lambda x: r.stocks.get_name_by_symbol(x))
    tickers_df['hold'] = True
    tickers_df['t_type'] = t_type

    tickers_df = pd.concat([tickers_df, current_tickers_df]).drop_duplicates().reset_index(drop=True)
    print(f"\n==============\nTOTAL WATCHLIST:\n{tickers_df[tickers_df['hold'] == False]}\n==============")
    status = updateData(tickersTable, tickers_df, DATABASE, ['ticker', 't_type', 'id'])

    if not status:
        print(f"\n==============\nTERMINATED: Exception at insert portfolio tickers\n==============")
        return False

    return tickers_df[['id', 'ticker', 'name']]


#### get portfolio data

def get_portfolio_data():
    logging.debug(f'getting data for portfolio')
    # get data
    d = r.account.get_open_stock_positions()
    df = pd.DataFrame.from_dict(d)
    df['id'] = df['instrument'].apply(lambda x: x.split('/')[-2])
    hold_ids = list(df['id'])

    prev_hold_ids = getData(tickersTable, rows={'hold': True, 't_type': 'equity'}, column='id')
    if not prev_hold_ids:  # empty table
        prev_hold_ids = []
    if sorted(hold_ids) != sorted(prev_hold_ids):
        update_portfolio_tickers(hold_ids, prev_hold_ids, t_type='equity')

    all_ids = getData(tickersTable, rows={'t_type': 'equity'}, column='id')
    watchlist_df = pd.DataFrame(np.setdiff1d(all_ids, hold_ids), columns=['id'])
    df = df.append(watchlist_df).reset_index(drop=True)
    print(f"\n==============\nEQUITIES WATCHLIST:\n{watchlist_df}\n==============")
    df['ticker'] = df['id'].apply(lambda x: getData(tickersTable, rows={'id': x}, column='ticker'))
    df['latest_price'] = r.stocks.get_latest_price(list(df['ticker']), priceType=None, includeExtendedHours=True)
    df = df[['ticker', 'average_buy_price', 'quantity', 'latest_price']]

    info_df = pd.DataFrame(r.stocks.get_quotes(list(df['ticker'])))
    df = pd.concat([df, info_df], axis=1)
    df['prev_close_price'] = df['adjusted_previous_close']
    df['prev_close_unadjusted'] = df['previous_close']
    df['datetime'] = pd.to_datetime(df['updated_at']).dt.tz_convert('US/Eastern')  #.dt.tz_localize(None)
    df['previous_close_date'] = pd.to_datetime(df['previous_close_date']).dt.date

    # convert type
    numerical_cols = ['average_buy_price', 'quantity', 'prev_close_price', 'prev_close_unadjusted',
                      'ask_price', 'ask_size', 'bid_price', 'bid_size', 'latest_price', 'last_trade_price',
                      'last_extended_hours_trade_price']
    df[numerical_cols] = df[numerical_cols].apply(pd.to_numeric)

    df = df[['datetime', 'ticker'] + numerical_cols + ['previous_close_date']]
    # df = df[['ticker'] + numerical_cols + ['previous_close_date']]

    # insert one row at a time to prevent sqlite database malformed error
    # for row in df.to_dict('records'):
    #     dbms.write_row('portfolio',row)
    # logging.debug(f'written to {DATABASE} db')

    return df


#### get crypto data

def get_crypto_data():
    def get_yesterday_midnight_price(ticker):
        df = pd.DataFrame(
            r.crypto.get_crypto_historicals(
                ticker, interval='5minute', span='week'))
        df['datetime'] = pd.to_datetime(df['begins_at']).dt.tz_convert('US/Eastern').dt.tz_localize(None)
        df = df.set_index('datetime')['close_price'].resample('D').last()
        yesterday = (datetime.today() - BDay(1)).strftime('%Y-%m-%d')
        return df.loc[yesterday]

    df = pd.DataFrame()
    crypto_df = pd.DataFrame(r.crypto.get_crypto_positions())
    df['id'] = crypto_df['currency'].apply(lambda x: x['id'])
    df['datetime'] = datetime.now(tz=pytz.timezone('US/Eastern'))#.replace(tzinfo=None)
    df['name'] = crypto_df['currency'].apply(lambda x: x['name'])
    df['ticker'] = crypto_df['currency'].apply(lambda x: x['code'])
    df['average_buy_price'] = crypto_df['cost_bases'].apply(lambda x: x[0]['direct_cost_basis'])
    df['quantity'] = crypto_df['quantity']
    df['prev_close_price'] = df['ticker'].apply(lambda x: get_yesterday_midnight_price(x))
    df['latest_price'] = df['ticker'].apply(lambda x: r.crypto.get_crypto_quote(x, info='mark_price'))

    # convert type
    numerical_cols = ['average_buy_price', 'quantity', 'prev_close_price', 'latest_price']
    df[numerical_cols] = df[numerical_cols].apply(pd.to_numeric)
    df['average_buy_price'] = df['average_buy_price'] / df['quantity']

    df = df[['datetime', 'name', 'ticker', 'average_buy_price', 'quantity', 'prev_close_price', 'latest_price']]
    # df = df[['name', 'ticker', 'average_buy_price', 'quantity', 'prev_close_price', 'latest_price']]

    return df


#### get options data

def get_options_data():
    # get data
    d = r.options.get_open_option_positions()
    df = pd.DataFrame.from_dict(d)
    df['option_id'] = df['option'].apply(lambda x: x.split('/')[-2])
    df = df.rename(columns={'chain_symbol': 'ticker', 'average_price': 'average_buy_price'})

    hold_ids = list(df['option_id'])

    prev_hold_ids = getData(tickersTable, rows={'hold': True, 't_type': 'option'}, column='id')
    if sorted(hold_ids) != sorted(prev_hold_ids):
        update_portfolio_tickers(hold_ids, prev_hold_ids, 'option')

    all_ids = getData(tickersTable, rows={'t_type': 'option'}, column='id')
    watchlist_df = pd.DataFrame(np.setdiff1d(all_ids, hold_ids), columns=['option_id'])
    watchlist_df['ticker'] = watchlist_df['option_id'].apply(
        lambda x: getData(tickersTable, rows={'id': x}, column='ticker'))
    df = df.append(watchlist_df).reset_index(drop=True)
    print(f"\n==============\nOPTIONS WATCHLIST:\n{watchlist_df}\n==============")
    info_df = pd.DataFrame([r.options.get_option_instrument_data_by_id(x) for x in df['option_id']])
    df['exp_date'] = info_df['expiration_date']
    df['strike_price'] = info_df['strike_price']
    df['option_type'] = info_df['type']
    df = df[['option_id', 'ticker', 'option_type', 'exp_date', 'strike_price',
             'quantity', 'average_buy_price']]

    market_data_df = pd.DataFrame()
    for option_id in df['option_id'].to_list():
        market_data_df = market_data_df.append(pd.DataFrame(r.options.get_option_market_data_by_id(option_id)),
                                               ignore_index=True)
    df = pd.concat([df, market_data_df], axis=1)
    df = df.rename(columns={'previous_close_price': 'prev_close_price', 'adjusted_mark_price': 'latest_price'})

    # convert type
    numerical_cols = ['strike_price', 'quantity', 'average_buy_price', 'latest_price', 'prev_close_price',
                      'break_even_price', 'ask_price', 'ask_size', 'bid_price', 'bid_size', 'high_price',
                      'last_trade_price', 'last_trade_size', 'low_price', 'open_interest', 'volume',
                      'chance_of_profit_long', 'chance_of_profit_short', 'delta', 'gamma',
                      'implied_volatility', 'rho', 'theta', 'vega']
    df[numerical_cols] = df[numerical_cols].apply(pd.to_numeric)

    df['average_buy_price'] = df['average_buy_price'] / 100

    df['datetime'] = datetime.now(tz=pytz.timezone('US/Eastern'))  #.replace(tzinfo=None)
    df['exp_date'] = pd.to_datetime(df['exp_date']).dt.date
    df['previous_close_date'] = pd.to_datetime(df['previous_close_date']).dt.date

    df = df[['datetime', 'option_id', 'ticker', 'option_type', 'exp_date'] + numerical_cols + ['previous_close_date']]
    # df = df[['option_id', 'ticker', 'option_type', 'exp_date'] + numerical_cols + ['previous_close_date']]
    return df


#### get portfolio summary data

def get_portfolio_summary_data():
    d = {}
    d['datetime'] = datetime.now(tz=pytz.timezone('US/Eastern'))#.replace(tzinfo=None)
    # d['datetime'] = pd.to_datetime(d['datetime'])
    d['username'] = 'sheryl'

    crypto_df = get_crypto_data()
    d['crypto_equity'] = (crypto_df['latest_price'] * crypto_df['quantity']).sum()
    d['crypto_equity_prev_close'] = (crypto_df['prev_close_price'] * crypto_df['quantity']).sum()

    stock_portfolio = r.profiles.load_portfolio_profile()

    equity_ext_hrs = stock_portfolio['extended_hours_equity']
    equity = stock_portfolio['equity']
    d['equity_latest'] = float(equity_ext_hrs if equity_ext_hrs else equity)
    d['equity_prev_close'] = float(stock_portfolio['adjusted_equity_previous_close'])

    #     d['equity_after_hrs_gain'] = d['equity_extended_hrs'] - float(stock_portfolio['equity'])
    d['withdrawable_amount'] = float(stock_portfolio['withdrawable_amount'])
    d['excess_margin'] = float(stock_portfolio['excess_margin'])
    d['excess_maintenance'] = float(stock_portfolio['excess_maintenance'])

    return pd.DataFrame(d, index=[0])


#### insert portfolio data
def insert_portfolio_data():
    login()  # custom robinhood login function

    portfolio_df = get_portfolio_data()
    status = insertData(portfolioTable, portfolio_df, DATABASE)
    if not status:
        print(f"==============\nTERMINATED: Exception at insert portfolio data\n==============")
        return False

    crypto_df = get_crypto_data()
    status = insertData(cryptoTable, crypto_df, DATABASE)
    if not status:
        print(f"==============\nTERMINATED: Exception at insert crypto data\n==============")
        return False

    options_df = get_options_data()
    status = insertData(optionsTable, options_df, DATABASE)
    if not status:
        print(f"==============\nTERMINATED: Exception at insert options data\n==============")
        return False

    summary_df = get_portfolio_summary_data()
    status = insertData(portfolioSummaryTable, summary_df, DATABASE)
    if not status:
        print(f"==============\nTERMINATED: Exception at insert portfolio summary data\n==============")
        return False

    # status = insert_yf_data()
    # if not status:
    #     print(f"==============\nTERMINATED: Exception at insert yf data\n==============")
    #     return False

    return True


##################
# INITIALIZE DATABASE
##################

if __name__ == "__main__":
    # initTables()
    login()  # location of robinhood login pickle file
    insert_yf_data()
    # insert_portfolio_data()

# else:
#     print("imported rs_db")