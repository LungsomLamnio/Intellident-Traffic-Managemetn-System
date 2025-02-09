import tkinter as tk
import requests
import string
import time
import math
import threading
import webbrowser
import os
from tkinter import messagebox
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY")


def meters_to_degrees_latitude(meters):
    return meters / 111320


def meters_to_degrees_longitude(meters, latitude):
    return meters / (111320 * math.cos(math.radians(latitude)))


def get_nearest_road(latitude, longitude, api_key):
    roads_url = f'https://roads.googleapis.com/v1/nearestRoads?points={latitude},{longitude}&key={api_key}'
    response = requests.get(roads_url)
    if response.status_code == 200:
        data = response.json()
        if 'snappedPoints' in data:
            return data['snappedPoints']
        else:
            return []
    else:
        print("Error fetching data from Roads API")
        return []

    try:
        response = requests.get(roads_url, timeout=10)  # Add timeout
        response.raise_for_status()  # Raise an exception for HTTP errors
        return response.json()  # Process the response as needed
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return None


def count_nearby_roads(latitude, longitude, api_key, range_m, max_snap_points=4):
    snapped_points = []
    unique_road_coords = set()

    lat_range = meters_to_degrees_latitude(range_m)
    lon_range = meters_to_degrees_longitude(range_m, latitude)

    directions = [(1, 0), (0, 1), (-1, 0), (0, -1)]  # Move north, east, south, west
    for dx, dy in directions:
        i = 0
        while True:
            lat = latitude + i * lat_range * dx
            lon = longitude + i * lon_range * dy
            points = get_nearest_road(lat, lon, api_key)

            for point in points:
                coords = (point['location']['latitude'], point['location']['longitude'])
                if coords not in unique_road_coords:
                    snapped_points.append(point)
                    unique_road_coords.add(coords)

                if len(snapped_points) >= max_snap_points:
                    break

            if len(snapped_points) >= max_snap_points or len(points) == 0:
                break

            i += 1
            time.sleep(0.1)
            if i > 100:  # Safeguard to prevent infinite loop in case fewer roads are available
                break

    num_roads = len(snapped_points)
    return snapped_points, num_roads


def get_traffic_data(latitude, longitude, api_key, retries=3):
    for _ in range(retries):
        traffic_url = f'https://maps.googleapis.com/maps/api/distancematrix/json?origins={latitude},{longitude}&destinations={latitude + 0.001},{longitude + 0.001}&departure_time=now&traffic_model=best_guess&key={api_key}'
        response = requests.get(traffic_url)
        if response.status_code == 200:
            data = response.json()
            if 'rows' in data and 'elements' in data['rows'][0] and 'duration_in_traffic' in \
                    data['rows'][0]['elements'][0]:
                traffic_intensity = data['rows'][0]['elements'][0]['duration_in_traffic']['value']
                if traffic_intensity > 0:
                    return traffic_intensity
            else:
                print("No traffic data available for the specified location")
        time.sleep(0.1)

    print("Error fetching data from Traffic API or all attempts returned 0 traffic intensity")
    return None


def determine_traffic_intensities(snapped_points, api_key):
    intensities = []
    for point in snapped_points:
        intensity = get_traffic_data(point['location']['latitude'], point['location']['longitude'], api_key)
        intensities.append(intensity if intensity is not None else 0)
    return intensities


class TrafficLightGUI:
    def __init__(self, master):
        self.master = master
        self.canvas = tk.Canvas(master, width=70, height=150)
        self.canvas.pack()
        self.colors = ["red", "yellow", "green"]
        self.current_color_index = 0
        self.draw_traffic_light()

        # Create a label for the countdown timer
        self.timer_label = tk.Label(master, text="", font=("Helvetica", 14))
        self.timer_label.pack()

    def draw_traffic_light(self):
        box_width = 50
        box_height = 175
        box_left = (70 - box_width) / 2
        box_top = (150 - box_height) / 2
        box_right = box_left + box_width
        box_bottom = box_top + box_height

        self.canvas.create_rectangle(box_left, box_top, box_right, box_bottom, fill="black")

        light_size = 20
        light_left = (70 - light_size) / 2
        light_top = box_top + 20
        light_bottom = light_top + light_size

        self.lights = [
            self.canvas.create_oval(light_left, light_top + i * (light_size + 40), light_left + light_size,
                                    light_bottom + i * (light_size + 40), fill="black")
            for i in range(3)
        ]

    def update_light(self, color, countdown_time=None):
        for light in self.lights:
            self.canvas.itemconfig(light, fill="black")
        color_index = self.colors.index(color)
        self.canvas.itemconfig(self.lights[color_index], fill=color)

        # Update the timer label if a countdown time is provided
        if countdown_time is not None:
            self.update_timer(countdown_time)
        else:
            self.timer_label.config(text="")  # Clear the timer when no countdown is needed

    def update_timer(self, time_left):
        if time_left > 0:
            self.timer_label.config(text=f"{time_left} sec")
        else:
            self.timer_label.config(text="")


def fetch_new_traffic_data(snapped_points, api_key, result_holder):
    """Fetch traffic data asynchronously and store the result."""
    new_intensities = determine_traffic_intensities(snapped_points, api_key)
    result_holder.append(new_intensities)

def update_traffic_lights(root, road_names, snapped_points, traffic_lights, api_key, life_cycle_seconds):
    intensities = determine_traffic_intensities(snapped_points, api_key)
    sorted_indices = sorted(range(len(intensities)), key=lambda i: intensities[i], reverse=True)

    total_roads = len(road_names)
    half_cycle_time = life_cycle_seconds / 2
    secondary_cycle_time = half_cycle_time / (total_roads - 1)

    new_data_holder = []

    for index in range(len(sorted_indices)):
        current_road_index = sorted_indices[index]
        road_name = road_names[current_road_index]
        ui_label = chr(65 + current_road_index)  # Converts index to A, B, C, etc.

        for i in range(total_roads):
            if i != current_road_index:
                traffic_lights[i].update_light("red")
        root.update()

        if index == 0:
            green_time = half_cycle_time
        else:
            green_time = secondary_cycle_time

        print(f"{ui_label} ({road_name}) green for {green_time} seconds.")
        for t in range(int(green_time), 0, -1):
            traffic_lights[current_road_index].update_light("green", countdown_time=t)
            root.update()
            time.sleep(1)

        print(f"{ui_label} ({road_name}) yellow for 5 seconds.")

        if index == len(sorted_indices) - 1:
            print("Fetching new traffic data during yellow light of the last road.")
            traffic_thread = threading.Thread(target=fetch_new_traffic_data,
                                              args=(snapped_points, api_key, new_data_holder))
            traffic_thread.start()

        for t in range(5, 0, -1):
            traffic_lights[current_road_index].update_light("yellow", countdown_time=t)
            root.update()
            time.sleep(1)

        traffic_lights[current_road_index].update_light("red")
        root.update()

    if new_data_holder:
        traffic_thread.join()
        intensities = new_data_holder[0]

        print("\nNext cycle data (updated traffic intensities):")
        for i, point in enumerate(snapped_points):
            road_coords = (point['location']['latitude'], point['location']['longitude'])
            traffic_intensity = intensities[i]
            ui_label = chr(65 + i)
            print(f"{ui_label} ({road_names[i]}): Coordinates: {road_coords} | Traffic Intensity: {traffic_intensity}")

        sorted_indices = sorted(range(len(intensities)), key=lambda i: intensities[i], reverse=True)

    print("\nStarting next cycle with updated traffic data.")
    root.after(1000, update_traffic_lights, root, road_names, snapped_points, traffic_lights, api_key,
               life_cycle_seconds)


def create_traffic_lights(root, road_names, snapped_points, api_key, life_cycle_seconds):
    traffic_lights = []
    for i in range(len(road_names)):
        frame = tk.Frame(root)
        frame.pack(pady=10)

        # Use generic road labels (e.g., "Road A", "Road B", etc.)
        ui_label = chr(65 + i)  # Converts index to A, B, C, etc.
        label = tk.Label(frame, text=f"Road {ui_label}")
        label.pack()

        traffic_light = TrafficLightGUI(frame)
        traffic_lights.append(traffic_light)

    update_traffic_lights(root, road_names, snapped_points, traffic_lights, api_key, life_cycle_seconds)





def get_nearest_major_road(latitude, longitude, api_key):
    """
    Attempt to find a nearby major road when the road is unnamed.
    """
    geocode_url = f'https://maps.googleapis.com/maps/api/geocode/json?latlng={latitude},{longitude}&key={api_key}'
    response = requests.get(geocode_url)

    if response.status_code == 200:
        data = response.json()
        if 'results' in data and data['results']:
            for result in data['results']:
                # Try to find a more detailed road name by checking address components
                for component in result['address_components']:
                    if "route" in component['types']:
                        return component['long_name']
                    # Look for sublocality, locality, etc. for hints if no road is found
                    elif "sublocality" in component['types']:
                        return f"Near {component['long_name']}"
                    elif "locality" in component['types']:
                        return f"Near {component['long_name']}"
        return "Unnamed Road (No nearby major road found)"
    else:
        return "Error retrieving road name"


def get_road_name_from_coordinates(latitude, longitude, api_key):
    """
    Retrieves the road name from coordinates using Reverse Geocoding API.
    If the road is unnamed, find the nearest major road.
    """
    geocode_url = f'https://maps.googleapis.com/maps/api/geocode/json?latlng={latitude},{longitude}&key={api_key}'
    response = requests.get(geocode_url)
    if response.status_code == 200:
        data = response.json()
        if 'results' in data and data['results']:
            # Extract the road name from the address components
            for component in data['results'][0]['address_components']:
                if "route" in component['types']:  # "route" indicates a road/street name
                    road_name = component['long_name']
                    if road_name == "Unnamed Road":
                        # If road is unnamed, try to find the nearest major road
                        return get_nearest_major_road(latitude, longitude, api_key)
                    return road_name
        return get_nearest_major_road(latitude, longitude, api_key)
    else:
        return "Error retrieving road name"


def get_road_name_or_landmark(lat, lon, api_key):
    """
    Use Google's Geocoding API to get the nearest road name.
    If the road is unnamed, find nearby landmarks or businesses and ensure names are unique.
    """
    geocode_url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lon}&key={api_key}"
    response = requests.get(geocode_url)

    if response.status_code == 200:
        data = response.json()
        if 'results' in data and len(data['results']) > 0:
            # Check if a road name is found
            for component in data['results'][0]['address_components']:
                if "route" in component['types']:
                    road_name = component['long_name']
                    if road_name != "Unnamed Road":
                        return road_name

        # If no road name, search for nearby landmarks or businesses
        business_names = find_nearby_businesses(lat, lon, api_key)
        if business_names:
            return business_names[0]  # Return the first unique business name found
        return "No identifiable name available"
    else:
        print(f"Error fetching road name from Geocoding API: {response.status_code}")
        return "Error retrieving road name"


def find_nearby_businesses(lat, lon, api_key, radius=500):
    """
    Use Google Places API to find nearby businesses or landmarks such as schools, colleges, hotels, restaurants, gyms, car showrooms, highways, overbridges, universities, and other relevant places.
    Returns a list of business names to ensure unique road naming.
    """
    types = [
        'school', 'university', 'car_dealer', 'restaurant',
        'shopping_mall', 'hospital', 'building', 'apartment', 'bridge'
    ]
    type_str = '|'.join(types)

    places_url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={lat},{lon}&radius={radius}&keyword={type_str}&key={api_key}"
    response = requests.get(places_url)

    if response.status_code == 200:
        data = response.json()
        if 'results' in data and len(data['results']) > 0:
            unique_businesses = set()
            for place in data['results']:
                place_types = place['types']
                if any(p_type in place_types for p_type in types):
                    unique_businesses.add(place['name'])  # Add unique names to the set
            return list(unique_businesses)  # Convert the set to a list for returning
        return []
    else:
        print(f"Error fetching nearby places from Places API: {response.status_code}")
        return []

def ensure_unique_road_name(road_name, used_names):
    """Ensure the road name is unique."""
    base_name = road_name
    counter = 1
    while road_name in used_names:
        road_name = f"{base_name} {counter}"
        counter += 1
    return road_name


def submit(latitude_entry, longitude_entry, box_id_entry, range_entry, life_cycle_entry, max_snap_points_entry):
    latitude = float(latitude_entry.get())
    longitude = float(longitude_entry.get())

    radius = float(range_entry.get())

    print(f"Location: Latitude: {latitude}, Longitude: {longitude}, Radius: {radius} meters")

    # Create the URL for the HTML file with the necessary parameters for location and radius
    html_content = f"""
    <html>
    <head>
      <title>Google Maps - Draw Circle with Traffic</title>
      <script src="https://maps.googleapis.com/maps/api/js?key={API_KEY}"></script>
      <script>
        function initMap() {{
          var map = new google.maps.Map(document.getElementById('map'), {{
            zoom: 15,
            center: {{lat: {latitude}, lng: {longitude}}}
          }});

          var trafficLayer = new google.maps.TrafficLayer();
          trafficLayer.setMap(map); // Add traffic layer

          var circle = new google.maps.Circle({{
            strokeColor: '#FF0000',
            strokeOpacity: 0.8,
            strokeWeight: 2,
            fillColor: '#FF0000',
            fillOpacity: 0.35,
            map: map,
            center: {{lat: {latitude}, lng: {longitude}}},
            radius: {radius}
          }});
        }}
      </script>
    </head>
    <body onload="initMap()">
      <div id="map" style="height: 100vh; width: 100%;"></div>
    </body>
    </html>
    """

    # Save the HTML content to a file
    file_name = "map_with_circle_and_traffic.html"
    try:
        with open(file_name, "w") as file:
            file.write(html_content)
        # Open the HTML file in the default browser
        webbrowser.open_new_tab(f"file://{os.path.abspath(file_name)}")
    except Exception as e:
        messagebox.showerror("Error", f"Failed to open the map file: {str(e)}")
    else:
        messagebox.showinfo("Success", f"Map file created and opened: {file_name}")

    traffic_box_id = box_id_entry.get()
    range_m = float(range_entry.get())
    life_cycle_seconds = int(life_cycle_entry.get())
    max_snap_points = int(max_snap_points_entry.get())

    print("Location (Latitude, Longitude):", latitude, longitude)
    print("Traffic Box ID:", traffic_box_id)
    print("Range of Device (in meters):", range_m)
    print("Total Life Cycle (in seconds):", life_cycle_seconds)

    google_maps_url = f"https://www.google.com/maps/@{latitude},{longitude},15z"
    webbrowser.open(google_maps_url)

    # Get the nearest roads
    snapped_points, num_roads = count_nearby_roads(latitude, longitude, API_KEY, range_m, max_snap_points=max_snap_points)

    if num_roads > 0:
        road_names = []
        used_names = set()  # To keep track of used names

        for point in snapped_points:
            road_name = get_road_name_or_landmark(point['location']['latitude'], point['location']['longitude'], API_KEY)

            # Ensure uniqueness
            road_name = ensure_unique_road_name(road_name, used_names)

            used_names.add(road_name)
            road_names.append(road_name)

        # Create UI labels for roads
        ui_labels = [f"Road {chr(65+i)}" for i in range(num_roads)]

        # Get traffic intensities for each road
        traffic_intensities = determine_traffic_intensities(snapped_points, API_KEY)

        # Print road details (name, coordinates, intensity) in the console with UI labels
        print(f"\nFound {num_roads} roads near the specified location:")
        for i, point in enumerate(snapped_points):
            road_coords = (point['location']['latitude'], point['location']['longitude'])
            traffic_intensity = traffic_intensities[i]
            print(f"{ui_labels[i]} ({road_names[i]}): Coordinates: {road_coords} | Traffic Intensity: {traffic_intensity}")

        # Start the traffic light simulation (with generic labels for UI)
        root = tk.Tk()
        root.title("Traffic Light Simulation")
        create_traffic_lights(root, road_names, snapped_points, API_KEY, life_cycle_seconds)
        root.mainloop()
    else:
        print("No roads found near the specified location.")



def autofill_lat_long(selection, latitude_entry, longitude_entry):
    locations = {
        "Narengi Tinali": (26.1786, 91.8293),
        "Zoo Road Tinali": (26.1749, 91.7767),
        "Jaynagar Chariali": (26.1223, 91.8061),
        "Beltola Chariali": (26.1286, 91.8013),
        "Mission Chariali(Tezpur)": (26.6608, 92.7755),
        "Baihata Chariali": (26.3449, 91.7163),
        "Ganesguri Chariali": (26.1498, 91.7852),
        "Maligaon Chariali": (26.1592, 91.6961),
        "Basistha Chariali": (26.1113, 91.7976),
        "Thana Chariali(Dibrugarh)": (27.4810, 94.9076)
    }

    if selection in locations:
        latitude, longitude = locations[selection]
        latitude_entry.delete(0, tk.END)
        latitude_entry.insert(0, str(latitude))
        longitude_entry.delete(0, tk.END)
        longitude_entry.insert(0, str(longitude))


def main():
    window = tk.Tk()
    window.title("Traffic Management System with Google Maps Circle")

    # Create the input fields
    tk.Label(window, text="Latitude:").grid(row=0, column=0)
    latitude_entry = tk.Entry(window)
    latitude_entry.grid(row=0, column=1)

    tk.Label(window, text="Longitude:").grid(row=1, column=0)
    longitude_entry = tk.Entry(window)
    longitude_entry.grid(row=1, column=1)

    tk.Label(window, text="Traffic Box ID:").grid(row=2, column=0)
    box_id_entry = tk.Entry(window)
    box_id_entry.grid(row=2, column=1)

    tk.Label(window, text="Range (meters):").grid(row=3, column=0)
    range_entry = tk.Entry(window)
    range_entry.grid(row=3, column=1)

    tk.Label(window, text="Life Cycle (seconds):").grid(row=4, column=0)
    life_cycle_entry = tk.Entry(window)
    life_cycle_entry.grid(row=4, column=1)

    tk.Label(window, text="Max Snap Points:").grid(row=5, column=0)
    max_snap_points_entry = tk.Entry(window)
    max_snap_points_entry.grid(row=5, column=1)

    # Add location recommendation dropdown
    tk.Label(window, text="Choose Location:").grid(row=6, column=0)
    location_options = [
        "Narengi Tinali", "Zoo Road Tinali", "Jaynagar Chariali", "Beltola Chariali",
        "Mission Chariali(Tezpur)", "Baihata Chariali", "Ganesguri Chariali",
        "Maligaon Chariali", "Basistha Chariali", "Thana Chariali(Dibrugarh)"
    ]
    location_var = tk.StringVar(window)
    location_var.set("Select a location")

    location_menu = tk.OptionMenu(window, location_var, *location_options,
                                  command=lambda selection: autofill_lat_long(selection, latitude_entry,
                                                                              longitude_entry))
    location_menu.grid(row=6, column=1)

    # Submit button to trigger the map update
    submit_button = tk.Button(window, text="Submit",
                              command=lambda: submit(latitude_entry, longitude_entry, box_id_entry, range_entry, life_cycle_entry, max_snap_points_entry))
    submit_button.grid(row=7, column=1)

    window.mainloop()


if __name__ == "__main__":
    main()