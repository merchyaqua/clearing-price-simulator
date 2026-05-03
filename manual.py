# All volume and size numbers are in raw units

import bisect
import copy


mushrooms_order_book = {
    "bids": {20: 43000,
             19: 17000,
             18: 6000,
             17: 5000,
             16: 10000,
             15: 5000,
             14: 10000,
             13: 7000},
    "asks": {12: 20000,
             13: 25000,
             14: 35000,
             15: 6000,
             16: 5000,
             17: 0,
             18: 10000,
             19: 12000
             }
}

flax_order_book = {
    "bids": {30: 30000, 29: 5000, 28: 12000, 27: 28000},
    "asks": {28: 40000, 31: 20000, 32: 20000, 33: 20000}
}

class OrderBook:

    def __init__(self, order_book) -> None:
        # create prefix sums over price
        # we are looking for CP for max traded
        self.order_book = order_book
        self.ask_prices = sorted(list(self.order_book["asks"].keys()))
        self.bid_prices = sorted(list(self.order_book["bids"].keys()))

        # For readability
        self.max_bid = max(order_book["bids"].keys())
        self.min_ask = min(order_book["asks"].keys())
        self.max_ask = max(order_book["asks"].keys())
        self.min_bid = min(order_book["bids"].keys())

        self.__construct_prefix_sums()

    def __construct_prefix_sums(self):
        sorted_bid_vol_pairs = sorted(list(self.order_book["bids"].items()), key=lambda x: x[0], reverse=True)
        bid_vol_cumulative = {sorted_bid_vol_pairs[0][0]: sorted_bid_vol_pairs[0][1]}
        running_sum = sorted_bid_vol_pairs[0][1]

        for bid, vol in sorted_bid_vol_pairs[1:]:
            running_sum += vol
            bid_vol_cumulative[bid] = running_sum
        self.bid_vol_cumulative = bid_vol_cumulative
        
        sorted_ask_vol_pairs = sorted(list(self.order_book["asks"].items()), key=lambda x: x[0], reverse=False)
        ask_vol_cumulative = {sorted_ask_vol_pairs[0][0]: sorted_ask_vol_pairs[0][1]}
        running_sum = sorted_ask_vol_pairs[0][1]

        for ask, vol in sorted_ask_vol_pairs[1:]:
            running_sum += vol
            ask_vol_cumulative[ask] = running_sum
        self.ask_vol_cumulative = ask_vol_cumulative

    def fill_all_orders_at_clearing_price(self):
        '''
        Returns a dictionary of price: trade volume allocated to orders (filling at clearing price).
        '''  
        # Filter all asks and bids that qualify.
        clearing_price = self.get_clearing_price()[0]
        order_book_asks = self.order_book["asks"]
        order_book_bids = self.order_book["bids"]
        asks = self.ask_prices[:bisect.bisect_right(self.ask_prices, clearing_price)]
        bids = self.bid_prices[bisect.bisect_left(self.bid_prices, clearing_price):]
        bids = bids[::-1]

        # Fill by price-time priority. Match lowest ask to highest bid, then move down each level as it fills.
        ask_fills = {price: 0 for price in (order_book_asks)}
        bid_fills = {price: 0 for price in (order_book_bids)}

        # Fill from the top of order book
        filling_ask_index = 0
        filling_bid_index = 0
        ask_price= asks[filling_ask_index]
        bid_price = bids[filling_bid_index]
        ask_volume = order_book_asks[ask_price]
        bid_volume = order_book_bids[bid_price]

        while filling_ask_index < len(asks) and filling_bid_index < len(bids):
            # Fill everything that demand and supply allows
            volume_traded = min(ask_volume, bid_volume)
            ask_fills[ask_price] += volume_traded
            bid_fills[bid_price] += volume_traded

            # Determine price levels to move onto to continue filling
            # Case supply > demand at this price level
            if ask_volume > bid_volume:
                # Fill all the bids
                ask_volume -= bid_volume
                # Move on to next bid
                filling_bid_index += 1 
                if filling_bid_index == len(bids):
                    break

                bid_price = bids[filling_bid_index]
                bid_volume = order_book_bids[bid_price]

            # Case demand > supply
            elif bid_volume > ask_volume:
                # fill all the asks
                bid_volume -= ask_volume
                # Move on to next ask level
                filling_ask_index += 1 
                if filling_ask_index == len(asks):
                    break

                ask_price= asks[filling_ask_index]
                ask_volume = order_book_asks[ask_price]

            elif ask_volume == bid_volume:
                # filled all the bids and asks 
                # no subtraction of volume cuz we move on to a new price and volume for both anyway
                filling_bid_index += 1 
                filling_ask_index += 1 
                if filling_bid_index == len(bids):
                    break
                if filling_ask_index == len(asks):
                    break

                ask_price= asks[filling_ask_index]
                bid_price = bids[filling_bid_index]
                ask_volume = order_book_asks[ask_price]
                bid_volume = order_book_bids[bid_price]

        return ask_fills, bid_fills

    def get_volume_of_bids_at_least(self, price):
        # Treating the cumulative volume as a step function to interpolate for a given price.
        # This means prices that don't have a current bid will return the cumulative volume of its ceiling (in the set)
        # bid prices are sorted ascending
        interpolation_price_index = bisect.bisect_left(self.bid_prices, price) 
        if interpolation_price_index == len(self.bid_prices): # no bids are at least that generous
            return 0
        interpolation_price = self.bid_prices[interpolation_price_index]
        return self.bid_vol_cumulative[interpolation_price]
    
    def get_volume_of_asks_at_most(self, price):
        interpolation_price_index = bisect.bisect_right(self.ask_prices, price) - 1
        if interpolation_price_index < 0: # no one is selling for at most this cheap price
            return 0
        interpolation_price = self.ask_prices[interpolation_price_index]
        return self.ask_vol_cumulative[interpolation_price]
    
    def get_clearing_price(self):
        clearing_price = 0
        max_volume_traded = 0
        # TODO: search only points of volume change. searching the highest price, scanning from the right, sample the volume just after a rising/falling edge.
        for price in range(self.min_ask, self.max_bid+1): # constraining search space - nobody is willing to selling below min_ask, so nothing would fill
            volume_traded = min(self.get_volume_of_asks_at_most(price), 
                                self.get_volume_of_bids_at_least(price))
            if volume_traded == max_volume_traded:
                # Helpful print to adjust volume so it does not shift clearing price to something less favourable
                print("Tie-break applies from", clearing_price,"to", price)
                clearing_price = max(price, clearing_price)
            elif volume_traded > max_volume_traded:
                clearing_price = price
                max_volume_traded = volume_traded
        return clearing_price, max_volume_traded, self.get_volume_of_asks_at_most(clearing_price), self.get_volume_of_bids_at_least(clearing_price)
    
def calculate_clearing_price(order_book):
    results = (OrderBook(order_book).get_clearing_price())
    return results

def add_order(old_order_book, side, price, size):
    order_book = copy.deepcopy(old_order_book)
    # Note: none of the other methods are on-line, so the filling method calls the clearing price method that recalculates all cumulatives, could be inefficient for many tests
    if price not in order_book[side]:
        order_book[side][price] = size
    else:
        order_book[side][price] += size
    return order_book

mushrooms = {"fair_value": 20,
             "fee": 0.1,
             "order_book": mushrooms_order_book}
flax = {"fair_value": 30,
             "fee": 0,
             "order_book": flax_order_book
             }

# Old clearing price
# calculate_clearing_price(mushrooms_order_book)
# calculate available float at given order price

def late_bid(product, side, order_price, size):
    # Adds the final bid to the order book, fills all orders with price-time priority and returns profit
    # side = 'bids' or 'asks'
    base_order_book = product["order_book"]
    order_book = add_order(base_order_book, side, order_price, size)
    print("Your order:", "bid", (order_price, size))
    clearing_price = OrderBook(order_book).get_clearing_price()[0]

    print("New clearing price:", clearing_price)
    ask_fills, bid_fills = (OrderBook(order_book).fill_all_orders_at_clearing_price())
    print("Ask fills:", ask_fills)
    print("Bid fills:",bid_fills)

    existing_level_size = base_order_book[side].get(order_price, 0)
    if side == "bids":
        my_fill_size = (bid_fills[order_price] - existing_level_size)
    elif side == "asks":
        my_fill_size = (ask_fills[order_price] - existing_level_size)

    print("Your fill:", my_fill_size)

    fees = product["fee"] * my_fill_size
    print("Fees:", fees)
    revenue = (product["fair_value"] - clearing_price) * my_fill_size
    profit = revenue - fees
    print("Revenue:", revenue)
    print("Profit:", profit)
    return profit

print("------FLAX---------")
late_bid(flax, "bids", 30, 9999)

print("-----MUSHROOMS---------")

# late_bid(mushrooms, "bids", 19, 40999)
for i in range(15, 21):
    late_bid(mushrooms, "bids", i, 19999)