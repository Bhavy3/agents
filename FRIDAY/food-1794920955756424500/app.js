// Featured menu for Food.
const dishes = [
  { name: "Roasted tomato soup", price: "$9" },
  { name: "Herb garden pasta", price: "$16" },
  { name: "Warm apple tart", price: "$8" }
];
const menu = document.querySelector('#menu');
for (const dish of dishes) {
  const item = document.createElement('li');
  item.textContent = `${dish.name} - ${dish.price}`;
  menu.append(item);
}
